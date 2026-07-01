from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
from pathlib import Path
from typing import Any

import aiohttp
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent.parent.parent / ".env")

PRIMARY_MODEL: str = os.getenv("SYNTHESIS_MODEL_PRIMARY")
FALLBACK_MODEL: str = os.getenv("SYNTHESIS_MODEL_FALLBACK")

OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")


LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "remote").lower()

LOCAL_LLM_URL: str = os.getenv("LOCAL_LLM_URL", "http://127.0.0.1:11434/api/generate")
LOCAL_MODEL_NAME: str = os.getenv(
    "LOCAL_MODEL_NAME", os.getenv("MODEL_NAME", "qwen2.5:7b")
)

from app.schemas.synthesis import CitationRef, SynthesisGap  # noqa: E402
from app.services.synthesis.gap_scorer import compute_gap_score  # noqa: E402
from app.services.synthesis.pattern_analysis import extract_cluster_themes  # noqa: E402
from app.services.synthesis.citation_validation import (  # noqa: E402
    validate_gap_citations,
    validate_gap_against_supported_papers,
    verify_gap_with_llm,
)
from app.services.analysis.scoring import (  # noqa: E402
    score_support,
    score_severity,
    score_actionability,
    score_novelty,
    score_citation_confidence,
    compute_overall_score,
    build_gap_score_breakdown,
)

logger = logging.getLogger(__name__)

# Minimum cluster size to warrant LLM gap generation
MIN_CLUSTER_SIZE_FOR_LLM = 2


class GapLLMClient:
    """Simple wrapper to provide the .generate() interface for citation validation."""

    async def generate(self, prompt: str, response_format: dict = None) -> str:
        # Use existing routing logic
        if LLM_PROVIDER == "local" or (not OPENROUTER_API_KEY and LOCAL_LLM_URL):
            return await _call_local_model(prompt)
        else:
            # Try primary then fallback
            last_exc = None
            for model_name in [PRIMARY_MODEL, FALLBACK_MODEL]:
                try:
                    return await _call_openrouter(prompt, model_name)
                except Exception as exc:
                    last_exc = exc
            raise last_exc or RuntimeError("All LLM models failed in client.")


# Shared aiohttp session (reused across all requests; avoids TLS overhead)
_http_session: aiohttp.ClientSession | None = None


async def _get_http_session() -> aiohttp.ClientSession:
    """Return a long-lived, shared aiohttp session with connection pooling."""
    global _http_session
    if _http_session is None or _http_session.closed:
        connector = aiohttp.TCPConnector(
            limit=30,
            ttl_dns_cache=300,
            enable_cleanup_closed=True,
        )
        _http_session = aiohttp.ClientSession(connector=connector)
    return _http_session


# Prompt helpers


def _build_cluster_context(cluster_papers: list[dict]) -> str:
    lines: list[str] = []
    for i, p in enumerate(cluster_papers, 1):
        title = p.get("title", "Unknown")
        year = p.get("year", "?")
        # Abstract: first 350 chars
        abstract = (p.get("abstract") or "")[:800].strip()
        limitations = "; ".join((p.get("normalized_limitations") or [])[:5])
        future_work = "; ".join((p.get("normalized_future_work") or [])[:5])
        methods_raw = (
            p.get("normalized_methods")
            or p.get("normalized_method")
            or ([p.get("method")] if p.get("method") else [])
        )
        methods = "; ".join((methods_raw or [])[:4])
        metrics = "; ".join((p.get("normalized_metrics") or [])[:4])
        datasets = "; ".join((p.get("normalized_datasets") or [])[:3])

        lines.append(
            f"[{i}] {title} ({year})\n"
            f"    Contribution: {abstract or 'N/A'}\n"
            f"    Methods: {methods or 'N/A'}\n"
            f"    Metrics: {metrics or 'N/A'}\n"
            f"    Datasets/Benchmarks: {datasets or 'N/A'}\n"
            f"    Limitations: {limitations or 'N/A'}\n"
            f"    Future work: {future_work or 'N/A'}"
        )
    return "\n\n".join(lines)


def _gap_prompt(
    cluster_id: int,
    cluster_papers: list[dict],
    topic: str,
    pattern: dict,
    themes: dict,
    other_themes: list[str] | None = None,
) -> str:
    context = _build_cluster_context(cluster_papers)
    n_papers = len(cluster_papers)

    top_methods = (
        ", ".join(str(m) for m in (pattern.get("top_methods") or [])[:5]) or "N/A"
    )
    top_limitations = (
        ", ".join(str(lim) for lim in (pattern.get("top_limitations") or [])[:5])
        or "N/A"
    )
    top_metrics = (
        ", ".join(str(m) for m in (pattern.get("top_metrics") or [])[:5]) or "N/A"
    )

    cluster_lims = (
        ", ".join(themes.get("top_limitations") or []) or "not yet identified"
    )
    cluster_fw = ", ".join(themes.get("top_future_work") or []) or "not yet identified"
    theme_label = themes.get("theme_label", "unspecified")

    other_themes_context = ""
    if other_themes:
        # Filter out empty or unspecified themes
        filtered_other = [t for t in other_themes if t and "unspecified" not in t.lower()]
        if filtered_other:
            distinct_other = sorted(list(set(filtered_other)))
            other_themes_context = (
                "\nDISTINCTNESS CONSTRAINT:\n"
                "To ensure research gaps are distinct across different clusters, here are themes of the other clusters in this literature review:\n"
                "  - " + "\n  - ".join(distinct_other) + "\n"
                "CRITICAL: Do NOT copy, duplicate, or heavily overlap with these themes or their titles. "
                "Ensure that your generated `theme_label` and `gap_title` are uniquely differentiated and specific to the unique details, applications, and papers of THIS cluster.\n"
            )

    return f"""You are an expert Research Analyst identifying unresolved research gaps from academic literature.

TASK
Analyze the {n_papers} papers below on "{topic}". Identify the single most critical, evidence-backed research gap in this cluster.

CONTEXT 
Field-wide patterns:
  Methods: {top_methods} | Limitations: {top_limitations} | Metrics: {top_metrics}

This cluster — {theme_label}:
  Shared limitations: {cluster_lims}
  Open future work:   {cluster_fw}
{other_themes_context}
PAPERS:
{context}

REASON INTERNALLY (do not output)
Before writing JSON, think through:
  a) What specific mechanism/assumption repeatedly fails across ≥2 papers?
  b) Is it a method conflict, empirical blindspot, or system failure?
  c) What must a researcher build or prove to close this gap?
  d) Which paper numbers [N] directly support each claim?
  e) Does every sentence start with a technical subject (method / system / metric)? If any sentence starts with "Paper", "Papers", "Multiple papers", "Several works", "[N]", or "According to", rewrite it.

QUALITY RULES

1. GROUNDING & CITATIONS (highest priority)
   • Cite [N] ONLY when paper [N]'s Contribution/Limitations/Future Work directly supports the claim.
   • Before citing [N], confirm: "Paper [N] says '___', which proves ___." If you cannot, remove the citation.
   • Never import a concept from general knowledge that does not appear in paper [N]'s text.
   • Place [N] ONLY at the END of a sentence — never mid-sentence, never as a subject/noun.
     ✗ "[1] shows..." / "According to [1]..." / "Paper [1] and [2] both show..."
     ✓ "Attention mechanisms degrade under distribution shift [1, 2]."
   • If fewer than 2 papers clearly support a claim, omit it.

2. SENTENCE SUBJECTS — ABSOLUTE RULE (no exceptions)
   Every sentence MUST begin with a technical subject: the method, system, algorithm, metric, or dataset.
   The following openings are FORBIDDEN in every field of the JSON output:
     ✗ "Papers [1] and [2]..."
     ✗ "Paper [N]..."
     ✗ "Multiple papers in this cluster..."
     ✗ "Several works in this cluster..."
     ✗ "[1] shows..." / "[N] highlight..."
     ✗ "According to [N]..."
   Correct form: lead with the technical subject, place the citation at the END of the sentence.
     ✓ "Monotone value-decomposition networks cannot represent non-monotone interactions at scale [1, 2]."
     ✓ "Standard benchmarks do not test credit-assignment fidelity beyond 16 agents [3]."

3. ANTI-HALLUCINATION (overrides all other rules)
   • Never invent numbers, percentages, or thresholds (e.g., ">20% drop") unless explicitly in the paper text above.
   • Never introduce technical terms not present in the cited paper's context block.
   • Use qualitative phrasing when figures are absent: "significant degradation", "markedly reduced performance".

4. SPECIFICITY — Name the exact failing mechanism.
   ✗ "Current methods do not scale well."
   ✓ "Attention-based coordination degrades substantially when agent count exceeds 64 due to quadratic message complexity [2]."

   NAME THE METHOD — ABSOLUTE RULE (no exceptions):
   Whenever a paper's contribution, method, or technique is mentioned, state its EXACT name (the algorithm, model, framework, architecture, or approach as named in the paper).
   NEVER use vague placeholders like "new methods", "proposed methods", "their approach", "a novel technique", or "new algorithms".
     ✗ "Papers [1] propose new methods but do not compare them against existing techniques."
     ✗ "The proposed approach in [1] lacks rigorous evaluation."
     ✓ "QMIX proposes monotone value decomposition but does not compare against non-monotone baselines [1]."
     ✓ "The Transformer-XL architecture achieves longer context but lacks evaluation on multi-domain benchmarks [2]."
   If the paper's method name is not explicitly stated in the provided context, use the most specific descriptive phrase available (e.g. "the attention-routing mechanism in [1]"), never just "methods" or "techniques".

5. MATHEMATICAL NOTATION
   • Preserve all variable names (|S|, |A|, γ, ε) and complexity expressions exactly as written.
   • Never simplify or transliterate Greek letters or exponent notation.

6. PROPOSED DIRECTION — Write 3–5 sentences covering:
   (1) What system/model/framework to build.
   (2) The methodology and experimental steps.
   (3) The benchmark/dataset/evaluation protocol.
   (4) A measurable success criterion.
   ✗ "Future work should explore better methods."
   ✓ "Design a transformer-based mixing network conditioned on local observation context using counterfactual baselines. Train end-to-end on SMAC-v2 with team sizes 8–128 under partial observability. Measure win-rate retention and per-agent credit fidelity, with success defined as staying within 10% of 8-agent baseline performance at 128 agents."

EXAMPLE RESPONSE
{{
  "theme_label": "Multi-Agent Credit Assignment",
  "gaps": [{{
    "gap_title": "Credit Assignment Collapse in Large Cooperative Teams",
    "description": "Cooperative MARL methods that rely on shared team reward fail to assign meaningful individual credit when more than 32 agents act simultaneously [1]. QMIX and VDN decompose the joint value function monotonically, which provably cannot represent non-monotone interactions that emerge at scale [2]. No public benchmark currently tests credit-assignment fidelity beyond 16 agents, leaving this scaling failure invisible in standard evaluations [1, 3].",
    "what_fails": "Monotone value-decomposition networks (QMIX, VDN) cannot represent non-monotone interactions when cooperative teams exceed ~32 members.",
    "why_it_exists": "The monotonicity constraint guarantees convergence but inadvertently caps representational capacity — a trade-off the field has not yet resolved.",
    "missing_piece": "A scalable non-monotone mixing architecture with formal credit-attribution guarantees, validated on benchmarks with 32–128 agents.",
    "pattern_detected": "Over-reliance on monotone value decomposition in large cooperative settings.",
    "proposed_direction": "Develop a transformer-based mixing network conditioned on local observation context using counterfactual baselines to isolate each agent's marginal contribution. Train end-to-end on SMAC-v2 with team sizes 8–128 under partial observability. Measure win-rate retention and per-agent credit fidelity across scales. Success is defined as maintaining win-rate within 10% of the 8-agent baseline at 128 agents.",
    "confidence_score": 0.82
  }}]
}}

YOUR OUTPUT
Return ONLY valid JSON — no markdown, no extra text. Produce EXACTLY ONE gap.
Every field must be a non-empty English sentence. Never output null, N/A, or leave fields empty.
{{
  "theme_label": "3–6 word technical theme for this cluster",
  "gaps": [{{
    "gap_title": "Precise technical title, max 12 words",
    "description": "A concise, evidence-backed paragraph that clearly defines the research gap. Cover: what specific method, assumption, or mechanism fails and under what conditions (cite [N]); why existing approaches cannot resolve it; and what evaluation or benchmark gap keeps the problem undetected. Use precise technical language, avoid vague filler phrases, and place each citation [N] at the end of the sentence it supports. Never open with a meta-sentence about the papers or cluster (e.g. \"Multiple papers in this cluster...\") — start directly with the technical problem.",
    "what_fails": "1–2 sentences: the exact mechanism, algorithm, or assumption that fails, and the conditions under which it breaks down.",
    "why_it_exists": "1–2 sentences: root cause (data scarcity / architectural limit / evaluation blindspot / theoretical constraint) and why the field has not resolved it yet.",
    "missing_piece": "One sentence: the specific artefact (dataset / metric / model / proof) that does not yet exist.",
    "pattern_detected": "One short phrase: the overarching trend across these papers.",
    "proposed_direction": "3–5 sentences: (1) what to build, (2) methodology, (3) evaluation protocol, (4) measurable success criterion.",
    "confidence_score": <float 0.0–1.0 reflecting evidence strength>
  }}]
}}"""


# LLM callers


async def _call_openrouter(prompt: str, model: str, *, _retries: int = 2) -> str:

    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not set in .env")

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 1500,
    }
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://research-agent.local",
        "X-Title": "Research Agent Synthesis",
    }

    session = await _get_http_session()

    for attempt in range(_retries + 1):
        async with session.post(
            "https://openrouter.ai/api/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=60),
        ) as resp:
            if resp.status == 429 and attempt < _retries:
                # Respect Retry-After, capped at 15 s
                retry_after = float(resp.headers.get("Retry-After", 8))
                wait = min(retry_after, 15.0)
                logger.warning(
                    "Model %s rate-limited (429). Retrying in %.1f s (attempt %d/%d).",
                    model,
                    wait,
                    attempt + 1,
                    _retries,
                )
                await asyncio.sleep(wait)
                continue  # retry

            if not resp.ok:
                body = await resp.text()
                raise aiohttp.ClientResponseError(
                    resp.request_info,
                    resp.history,
                    status=resp.status,
                    message=f"OpenRouter error for model '{model}': {body[:400]}",
                )

            raw = await resp.json()
            return raw["choices"][0]["message"]["content"].strip()

    raise RuntimeError(f"Model {model} exhausted all retries.")


async def _call_local_model(prompt: str) -> str:
    """POST to a local Ollama-compatible endpoint."""
    payload = {
        "model": LOCAL_MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 1400},
    }
    session = await _get_http_session()
    async with session.post(
        LOCAL_LLM_URL,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=aiohttp.ClientTimeout(total=90),
    ) as resp:
        resp.raise_for_status()
        raw = await resp.json()
        return str(raw.get("response") or raw.get("content") or "").strip()


async def _call_llm(prompt: str) -> str:
    if LLM_PROVIDER == "local" or (not OPENROUTER_API_KEY and LOCAL_LLM_URL):
        return await _call_local_model(prompt)

    # Build model chain: PRIMARY → FALLBACK
    model_chain = list(dict.fromkeys([PRIMARY_MODEL, FALLBACK_MODEL]))

    last_exc: Exception | None = None
    for model in model_chain:
        try:
            return await _call_openrouter(prompt, model)
        except Exception as exc:
            logger.warning("Model %s failed: %s", model, exc)
            last_exc = exc

    raise RuntimeError(f"All LLM models failed. Last error: {last_exc}")


def _extract_json(text: str) -> dict:
    # Strip markdown code fences if present
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def _clean_val(v: Any, default: str = "") -> str:
    if v is None:
        return default
    s = re.sub(r"(?i)\bundefined\b", "", str(v)).strip()
    if not s:
        return default
    lower_s = s.lower()
    junk = {
        "null",
        "[object object]",
        "none",
        "n/a",
        "unknown",
        "string",
        "empty",
        "all",
        "any",
        "javascript:void(0)",
    }
    if lower_s in junk or re.sub(r"[^a-z0-9]", "", lower_s) in junk:
        return default
    return s


_PAPER_SUBJECT_RE = re.compile(
    r"(?i)"
    r"(?:"
    r"(?:papers?\s*(?:\[\d+\]\s*(?:,\s*|and\s*|&\s*)?)*\s*(?:and\s*)?(?:\[\d+\])?\s*(?:both\s+)?(?:highlight|show|demonstrate|find|suggest|indicate|reveal|note|report|argue|propose|identify|observe|confirm|support|illustrate|establish|present|describe)\s*)"  # Papers [1] and [2] highlight
    r"|(?:multiple\s+papers?(?:\s+in\s+this\s+cluster)?\s*,?\s*(?:including\s+(?:\[\d+\]\s*(?:,\s*|and\s*)?)+)?\s*)"  # Multiple papers in this cluster, including [1],
    r"|(?:several\s+works?(?:\s+in\s+this\s+cluster)?\s*)"  # Several works in this cluster
    r"|(?:according\s+to\s+(?:\[\d+\]\s*(?:,\s*|and\s*)?)+,?\s*)"  # According to [1],
    r"|(?:(?:\[\d+\]\s*(?:,\s*|and\s*)?)+\s+(?:show|highlight|demonstrate|find|suggest|indicate)\s*)"  # [1] and [2] show
    r")",
    re.VERBOSE,
)


def _strip_paper_subject_sentences(text: str) -> str:
    """Remove paper-subject preambles from every sentence in *text*.

    Transforms:
        'Papers [1] and [2] highlight the challenge of X.' -> 'The challenge of X.'
        'According to [1], Y fails.'                       -> 'Y fails.'
    """
    if not text:
        return text

    # Split into sentences (keep delimiters)
    sentences = re.split(r"(?<=[.!?])\s+", text)
    cleaned: list[str] = []
    for sentence in sentences:
        stripped = _PAPER_SUBJECT_RE.sub("", sentence).strip()
        if stripped:
            # Capitalise the first letter if it was lowercased by stripping
            cleaned.append(stripped[0].upper() + stripped[1:])
        else:
            # Safe Fallback: If stripping removes the entire sentence, keep original
            cleaned.append(sentence)
    return " ".join(cleaned)


# Evidence helpers


def _extract_and_verify_citations(text: str, papers: list[dict]) -> set[int]:
    valid: set[int] = set()
    for m in re.finditer(r"\[(\d+)\]", text):
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(papers):
            valid.add(idx)
    return valid


def _build_evidence(cluster_papers: list[dict]) -> dict:
    return {
        "recurring_limitations": [
            lim for p in cluster_papers for lim in p.get("normalized_limitations", [])
        ],
        "recurring_future_work": [
            f for p in cluster_papers for f in p.get("normalized_future_work", [])
        ],
        "dominant_assumptions": [
            a for p in cluster_papers for a in p.get("normalized_assumptions", [])
        ],
        "missing_metrics": [
            m for p in cluster_papers for m in p.get("normalized_metrics", [])
        ],
        "missing_datasets": [
            d for p in cluster_papers for d in p.get("normalized_datasets", [])
        ],
        "weak_baselines": [
            b for p in cluster_papers for b in p.get("normalized_baselines", [])
        ],
    }


def _gap_category(evidence: dict) -> str:
    text = str(evidence).lower()
    if any(t in text for t in ["metric", "baseline", "evaluation", "reward"]):
        return "evaluation"
    if any(t in text for t in ["deployment", "safe", "robust", "real-world"]):
        return "deployment"
    return "methodology"


def _score_from_evidence(
    cluster_papers: list[dict], cluster_id: int = -1, text: str = ""
) -> float:
    if not cluster_papers:
        return 0.0
    evidence = _build_evidence(cluster_papers)
    category = _gap_category(evidence)
    s_support = score_support(cluster_papers)
    s_severity = score_severity(category, evidence)
    s_action = score_actionability(category, evidence)
    s_novelty = score_novelty(cluster_papers)
    valid_cits = _extract_and_verify_citations(text, cluster_papers)
    cit_signal = len(valid_cits) / max(1, len(cluster_papers))
    s_cite = score_citation_confidence(cluster_papers)
    raw_score = compute_overall_score(
        s_support, s_severity, s_action, s_novelty, s_cite * (0.7 + 0.3 * cit_signal)
    )
    confidence = 1 / (1 + math.exp(-0.5 * (raw_score - 2.5)))
    return round(min(0.99, max(0.1, confidence)), 2)


def _make_citations(
    papers: list[dict], cited_indices: set[int] | None = None
) -> list[CitationRef]:
    source_papers = (
        [papers[i] for i in sorted(cited_indices) if 0 <= i < len(papers)]
        if cited_indices
        else papers[:5]
    )
    refs: list[CitationRef] = []
    for p in source_papers:
        evidence = (p.get("normalized_limitations") or [])[:2] + (
            p.get("normalized_future_work") or []
        )[:2]
        refs.append(
            CitationRef(
                paper_id=p.get("paper_id"),
                title=p.get("title", "Unknown"),
                year=p.get("year"),
                source=p.get("source"),
                venue=p.get("venue") or "Unknown Venue",
                citation_count=p.get("citation_count") or 0,
                url=p.get("url"),
                extracted_evidence=evidence,
            )
        )
    return refs


# Heuristic fallback gap
def _heuristic_gap(
    cluster_id: int,
    papers: list[dict],
    topic: str,
    gap_id: str,
    score: float,
    citations: list[CitationRef],
    paper_ids: list[str],
) -> SynthesisGap:
    from collections import Counter

    lim_c: Counter[str] = Counter()
    fw_c: Counter[str] = Counter()
    for p in papers:
        for lim in p.get("normalized_limitations", []):
            lim_c[lim] += 1
        for fw in p.get("normalized_future_work", []):
            fw_c[fw] += 1

    top_lim = lim_c.most_common(1)
    top_fw = fw_c.most_common(1)
    lim_text = top_lim[0][0] if top_lim else "unclear limitations"
    fw_text = top_fw[0][0] if top_fw else "unspecified future work"

    gap_fields = {
        "description": (
            f"Across {len(papers)} papers in this cluster, a recurring limitation is '{lim_text}'. "
            f"Authors frequently cite '{fw_text}' as open future work."
        ),
        "what_fails": lim_text,
        "why_it_exists": "This limitation appears repeatedly without resolution across the surveyed literature.",
        "missing_piece": fw_text,
        "proposed_direction": f"Address '{lim_text}' through a targeted study focused on '{fw_text}'.",
    }
    evidence = _build_evidence(papers)
    return SynthesisGap(
        gap_id=gap_id,
        gap_title=f"Unresolved gap in {topic}: {lim_text[:60]}",
        description=gap_fields["description"],
        what_fails=gap_fields["what_fails"],
        why_it_exists=gap_fields["why_it_exists"],
        missing_piece=gap_fields["missing_piece"],
        pattern_detected=f"Recurring limitation: {lim_text}",
        proposed_direction=gap_fields["proposed_direction"],
        confidence_score=score,
        cluster_id=cluster_id,
        supporting_papers=paper_ids,
        citations=citations,
        score_breakdown=build_gap_score_breakdown(
            papers, evidence, _gap_category(evidence)
        ),
        citation_validation=validate_gap_citations(gap_fields, citations),
        cross_paper_validation=validate_gap_against_supported_papers(
            gap_fields, papers
        ),
        llm_verification={"status": "unvalidated", "reason": "Heuristic fallback"},
    )


# Main gap generator (per cluster)


async def generate_gaps_for_cluster(
    cluster_id: int,
    cluster_papers: list[dict],
    topic: str,
    pattern: Any = {},
    all_papers: list[dict] | None = None,
    force_heuristic: bool = False,
    other_themes: list[str] | None = None,
    precalculated_themes: dict | None = None,
) -> tuple[list[SynthesisGap], str | None]:

    gap_serial = f"GAP-{cluster_id + 1:03d}"
    _all_papers = all_papers or cluster_papers

    confidence_score = compute_gap_score(cluster_papers, _all_papers)

    # Heuristic themes for prompt injection
    themes = precalculated_themes or extract_cluster_themes(cluster_papers)

    pattern_data = (
        pattern
        if isinstance(pattern, dict)
        else (pattern.model_dump() if hasattr(pattern, "model_dump") else {})
    )

    # Skip tiny clusters or those outside top K — use heuristic only
    if force_heuristic or len(cluster_papers) < MIN_CLUSTER_SIZE_FOR_LLM:
        fallback = _heuristic_gap(
            cluster_id,
            cluster_papers,
            topic,
            gap_serial,
            confidence_score,
            _make_citations(cluster_papers),
            [p.get("paper_id") or p.get("title", "") for p in cluster_papers],
        )
        return [fallback], None

    try:
        prompt = _gap_prompt(
            cluster_id,
            cluster_papers,
            topic,
            pattern_data,
            themes,
            other_themes=other_themes,
        )

        raw: str | None = None
        last_exc: Exception | None = None

        if LLM_PROVIDER == "local" or (not OPENROUTER_API_KEY and LOCAL_LLM_URL):
            raw = await _call_local_model(prompt)
        else:
            for model_name in [PRIMARY_MODEL, FALLBACK_MODEL]:
                try:
                    raw = await _call_openrouter(prompt, model_name)
                    break
                except Exception as exc:
                    last_exc = exc
                    logger.warning("Model %s failed: %s", model_name, exc)

        if raw is None:
            raise RuntimeError(f"All LLM models failed: {last_exc}")

        data = _extract_json(raw)

        if isinstance(data, dict) and "gaps" in data:
            llm_theme_label: str | None = _clean_val(data.get("theme_label")) or None
            data_list = data.get("gaps", [])
        else:
            llm_theme_label = (
                _clean_val(data.get("theme_label")) if isinstance(data, dict) else None
            )
            data_list = (
                [data]
                if isinstance(data, dict)
                else (data if isinstance(data, list) else [])
            )

        gaps_out: list[SynthesisGap] = []
        for idx, gap_data in enumerate(data_list):
            if not isinstance(gap_data, dict):
                continue

            text_content = (
                f"{gap_data.get('description', '')} "
                f"{gap_data.get('what_fails', '')} "
                f"{gap_data.get('why_it_exists', '')} "
                f"{gap_data.get('missing_piece', '')} "
                f"{gap_data.get('proposed_direction', '')}"
            )
            cited_indices = sorted(
                list(_extract_and_verify_citations(text_content, cluster_papers))
            )
            if len(cited_indices) < 1:
                cited_indices = list(range(min(2, len(cluster_papers))))

            citations = _make_citations(
                cluster_papers, cited_indices=set(cited_indices)
            )
            cited_paper_ids = [
                cluster_papers[i].get("paper_id") or cluster_papers[i].get("title", "")
                for i in cited_indices
            ]

            mapping = {
                old_idx + 1: new_idx + 1
                for new_idx, old_idx in enumerate(cited_indices)
            }

            def renumber_text(text: str) -> str:
                if not text:
                    return text

                def _replace(m: re.Match) -> str:
                    remapped = mapping.get(int(m.group(1)))
                    return f"[{remapped}]" if remapped is not None else ""

                return re.sub(r"\[(\d+)\]", _replace, text).strip()

            def clean(key: str, default: str = "") -> str:
                return _clean_val(gap_data.get(key)) or default

            gap_fields_for_val = {
                "what_fails": clean("what_fails"),
                "missing_piece": clean("missing_piece"),
            }
            cross_val = validate_gap_against_supported_papers(
                gap_fields_for_val, cluster_papers
            )

            base_score = _score_from_evidence(cluster_papers, cluster_id, text_content)
            try:
                llm_conf = float(gap_data.get("confidence_score", base_score))
            except (ValueError, TypeError):
                llm_conf = base_score

            # Blend objective evidence score with the gap-specific LLM confidence
            final_score = round(0.6 * base_score + 0.4 * llm_conf, 2)

            # Apply penalty if the gap is potentially addressed by newer papers
            if cross_val.get("status") == "potentially_addressed":
                final_score = round(final_score * 0.85, 2)

            evidence = _build_evidence(cluster_papers)
            score_breakdown = build_gap_score_breakdown(
                cluster_papers, evidence, _gap_category(evidence)
            )
            gap_fields = {
                "gap_title": clean(
                    "gap_title", f"Research gap in cluster {cluster_id}"
                ),
                "description": _strip_paper_subject_sentences(renumber_text(clean("description"))),
                "what_fails": _strip_paper_subject_sentences(renumber_text(clean("what_fails"))),
                "why_it_exists": _strip_paper_subject_sentences(renumber_text(clean("why_it_exists"))),
                "missing_piece": renumber_text(clean("missing_piece")),
                "pattern_detected": clean("pattern_detected"),
                "proposed_direction": _strip_paper_subject_sentences(renumber_text(clean("proposed_direction"))),
            }

            gaps_out.append(
                SynthesisGap(
                    gap_id=f"{gap_serial}-{idx + 1}",
                    gap_title=gap_fields["gap_title"],
                    description=gap_fields["description"],
                    what_fails=gap_fields["what_fails"],
                    why_it_exists=gap_fields["why_it_exists"],
                    missing_piece=gap_fields["missing_piece"],
                    pattern_detected=gap_fields["pattern_detected"],
                    proposed_direction=gap_fields["proposed_direction"],
                    confidence_score=final_score,
                    cluster_id=cluster_id,
                    supporting_papers=cited_paper_ids,
                    citations=citations,
                    score_breakdown=score_breakdown,
                    citation_validation=validate_gap_citations(gap_fields, citations),
                    cross_paper_validation=cross_val,
                    llm_verification=await verify_gap_with_llm(
                        gap_fields, citations, GapLLMClient()
                    ),
                )
            )

        return gaps_out, llm_theme_label

    except Exception as exc:
        logger.warning("LLM gap generation failed for cluster %d: %s", cluster_id, exc)
        fallback = _heuristic_gap(
            cluster_id,
            cluster_papers,
            topic,
            gap_serial,
            confidence_score,
            _make_citations(cluster_papers),
            [p.get("paper_id") or p.get("title", "") for p in cluster_papers],
        )
        return [fallback], None


async def generate_all_gaps(
    papers: list[dict],
    labels: list[int],
    topic: str,
    pattern: Any = {},
    top_k: int = 5,
    all_papers: list[dict] | None = None,
) -> tuple[list[SynthesisGap], dict[int, str]]:

    from collections import defaultdict

    _all = all_papers or papers
    cluster_map: dict[int, list[dict]] = defaultdict(list)
    for paper, label in zip(papers, labels):
        if label != -1:
            cluster_map[int(label)].append(paper)

    if not cluster_map:
        cluster_map[0] = papers

    # Sort clusters by size descending to prioritise LLM calls for the largest clusters.
    sorted_clusters = sorted(cluster_map.items(), key=lambda x: len(x[1]), reverse=True)

    # Pre-calculate themes for all clusters to provide distinctness constraints
    cluster_themes = {}
    for cid, cprs in sorted_clusters:
        cluster_themes[cid] = extract_cluster_themes(cprs)

    # Process all clusters with the LLM for maximum gap coverage
    max_llm_clusters = 10

    # Use a semaphore to limit concurrent LLM calls to prevent aggressive rate limits
    sem = asyncio.Semaphore(3)

    async def _process_cluster(i: int, cid: int, cprs: list[dict]):
        force_heuristic = i >= max_llm_clusters
        other_themes_list = [
            t.get("theme_label")
            for other_cid, t in cluster_themes.items()
            if other_cid != cid and t.get("theme_label")
        ]
        async with sem:
            try:
                # Add a small stagger to prevent sending all requests at the exact same millisecond
                if not force_heuristic and i > 0:
                    await asyncio.sleep(0.5 * min(i, 5))
                return await generate_gaps_for_cluster(
                    cid,
                    cprs,
                    topic,
                    pattern,
                    _all,
                    force_heuristic=force_heuristic,
                    other_themes=other_themes_list,
                    precalculated_themes=cluster_themes.get(cid),
                )
            except Exception as e:
                return e

    # Process all clusters concurrently
    tasks = [_process_cluster(i, cid, cprs) for i, (cid, cprs) in enumerate(sorted_clusters)]
    results = await asyncio.gather(*tasks)

    gaps: list[SynthesisGap] = []
    llm_theme_labels: dict[int, str] = {}

    # Pair results with the same sorted_clusters order used when collecting them
    for (cid, _), res in zip(sorted_clusters, results):
        if isinstance(res, Exception):
            logger.error("Error generating gaps for cluster %d: %s", cid, res)
            continue
        cluster_gaps, theme_label = res
        if isinstance(cluster_gaps, list):
            gaps.extend(cluster_gaps)
        if theme_label:
            llm_theme_labels[cid] = theme_label

    # Sort by confidence, then return all generated gaps
    sorted_gaps = sorted(gaps, key=lambda g: g.confidence_score, reverse=True)
    return sorted_gaps, llm_theme_labels


async def label_cluster(cluster_papers: list[dict], topic: str) -> dict:

    context = "\n".join(
        [
            f"Title: {p.get('title')}\nAbstract: {(p.get('abstract') or '')[:300]}…"
            for p in cluster_papers[:5]
        ]
    )
    prompt = f"""Identify the core research theme and the main shared technical limitation for this cluster.
TOPIC: {topic}
PAPERS:
{context}

Return ONLY a valid JSON object:
{{
  "theme_label": "3-5 word technical theme",
  "top_limitation": "One technical sentence describing the main shared gap/limitation"
}}"""
    try:
        raw = await _call_llm(prompt)
        data = _extract_json(raw)
        return {
            "theme_label": _clean_val(data.get("theme_label"), "unspecified gap"),
            "top_limitations": [data.get("top_limitation")]
            if data.get("top_limitation")
            else [],
            "paper_count": len(cluster_papers),
        }
    except Exception as exc:
        logger.warning("LLM cluster labeling failed: %s", exc)
        return {
            "theme_label": "Research cluster",
            "top_limitations": [],
            "paper_count": len(cluster_papers),
        }
