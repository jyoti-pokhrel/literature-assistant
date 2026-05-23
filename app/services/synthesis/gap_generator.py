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

PRIMARY_MODEL: str = os.getenv("SYNTHESIS_MODEL_PRIMARY") or "google/gemini-2.5-pro"
FALLBACK_MODEL: str = os.getenv("SYNTHESIS_MODEL_FALLBACK") or "anthropic/claude-3.5-sonnet"

OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")

MODEL_NAME: str = os.getenv("MODEL_NAME", "google/gemini-flash-1.5")

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
    for i, p in enumerate(cluster_papers[:8], 1):
        title = p.get("title", "Unknown")
        year = p.get("year", "?")
        # Abstract: first 350 chars
        abstract = (p.get("abstract") or "")[:350].strip()
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
) -> str:
    context = _build_cluster_context(cluster_papers)
    n_papers = min(len(cluster_papers), 8)

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

    return f"""You are an expert Research Analyst specializing in identifying unresolved research gaps from academic literature.

Your task: Analyze the {n_papers} papers below on the topic "{topic}" and produce precise, highly-critical, evidence-backed research gap that represents the most significant unresolved problem in this cluster.

LITERATURE CONTEXT
Global field patterns:
  - Dominant methods:     {top_methods}
  - Dominant limitations: {top_limitations}
  - Dominant metrics:     {top_metrics}

This cluster's theme: {theme_label}
  - Shared limitations:  {cluster_lims}
  - Open future work:    {cluster_fw}

PAPERS IN THIS CLUSTER:
{context}

STEP 1 — REASON FIRST (internal, not output)
Before writing the JSON, think through:
  a) What specific mechanism, component, or assumption repeatedly fails across ≥2 papers?
  b) Is it a method conflict, empirical blindspot, system failure, or interaction failure?
  c) What would a researcher need to build or prove to close this gap?
  d) Which paper numbers [N] directly support each claim?

STEP 2 — QUALITY RULES

▸ GROUNDING (most important rule):
  A citation [N] is ONLY valid if the claim in that sentence is directly supported by
  paper [N]'s "Contribution", "Limitations", or "Future work" text shown above.
  ✗ NEVER cite a paper just because it is in the cluster — check its actual content.
  ✗ NEVER cite a CNN paper to support a claim about Transformers (or vice versa).
  ✗ If fewer than 2 papers clearly support a claim, do NOT make that claim.
  ✓ Only cite [N] when you can complete this test: "Paper [N] says '___', which proves ___."

▸ ANTI-HALLUCINATION (CRITICAL):
  ✗ NEVER invent or hallucinate specific numbers, percentages (e.g., ">20% drop"), or metrics unless they are EXPLICITLY written in the paper context provided above.
  ✗ NEVER introduce specific technical concepts (like "partial observability") unless they actually appear in the text for the cited paper.
  ✓ Use qualitative terms (e.g., "significant degradation", "robustness drop") if exact numbers are not provided in the abstract.

▸ SPECIFICITY — Every claim must name the exact mechanism that fails:
  ✗ BAD:  "Current methods do not scale well."
  ✓ GOOD: "Attention-based coordination mechanisms degrade by >35% throughput when
           agent count exceeds 64 due to quadratic message complexity [2]."

▸ MATHEMATICAL RIGOR & NOTATION PRESERVATION (CRITICAL):
  ✓ ALWAYS preserve original variable names (|S|, |A|, |B|, \gamma, \epsilon) and mathematical notation exactly as they appear in the paper abstracts.
  ✓ NEVER simplify complexity notation; if a paper mentions O~(|S||A||B|(1-gamma)^{-3}epsilon^{-2}), do NOT change it to "sab(1-gamma-3epsilon-2)".
  ✓ Ensure all exponents, subscripts, and superscripts are correctly represented using standard text or LaTeX-style notation (e.g., ^-3, _0).
  ✗ NEVER substitute Greek letters with plain English words if the symbol is provided.

▸ CITATIONS — One [N] per sentence, placed at the sentence end:
  ✗ BAD:  "Paper [1] and [2] both show this."
  ✓ GOOD: "Transformer-based policies fail to generalize across environment shifts [1].
           Reward shaping mitigates this but introduces instability under partial
           observability [3]."

▸ DESCRIPTION — Write exactly 5 sentences following this structure:
    Sentence 1: State the core technical failure that repeats across papers [N].
    Sentence 2: Explain WHY the current approach hits this limit, with evidence [N].
    Sentence 3: Show a specific empirical or theoretical consequence [N].
    Sentence 4: Identify what is missing (dataset / metric / method / theory) [N].
    Sentence 5: Cite the paper(s) whose future-work or limitation statements confirm why
                existing approaches cannot close this gap without a new direction [N].

▸ PROPOSED DIRECTION — Must describe a concrete experiment, not a wish:
  ✗ BAD:  "Future work should explore better methods."
  ✓ GOOD: "Design a hierarchical credit-assignment framework that decouples
           individual rewards from team rewards and evaluate it on SMAC-v2
           with agent counts from 8 to 128."

EXAMPLE OF A COMPLETE HIGH-QUALITY RESPONSE
{{
  "theme_label": "Multi-Agent Credit Assignment",
  "gaps": [
    {{
      "gap_title": "Credit Assignment Collapse in Large Cooperative Teams",
      "description": "Cooperative MARL methods that rely on shared team reward fail to assign meaningful individual credit when more than 32 agents act simultaneously [1]. QMIX and VDN decompose the joint value function monotonically, which provably cannot represent non-monotone team interactions that emerge at scale [2]. Empirical evaluation shows a >40% drop in win rate on SMAC hard maps when teams exceed 20 units, a regime none of the surveyed methods were benchmarked on [3]. No public benchmark currently tests credit-assignment fidelity beyond 16 agents, leaving the scaling failure invisible in standard evaluations [1]. Existing value-decomposition architectures cannot be extended to handle this without redesigning the mixing network to allow conditional, non-monotone credit [2].",
      "what_fails": "Monotone value-decomposition networks (QMIX, VDN) cannot represent non-monotone interactions that emerge when cooperative agent teams exceed ~32 members.",
      "why_it_exists": "The monotonicity constraint was introduced to guarantee convergence but inadvertently caps representational capacity, a trade-off the field has not yet resolved.",
      "missing_piece": "A scalable, non-monotone mixing architecture with formal credit-attribution guarantees, validated on benchmarks with 32–128 agents.",
      "pattern_detected": "Over-reliance on monotone value decomposition in large cooperative settings.",
      "proposed_direction": "Develop a transformer-based mixing network that conditions credit assignment on local observation context and evaluate it on SMAC-v2 across team sizes from 8 to 128 agents.",
      "confidence_score": 0.82
    }}
  ]
}}

YOUR OUTPUT
Return ONLY the JSON object below — no markdown fences, no extra text.
Produce EXACTLY ONE gap in the "gaps" array — the single most critical, well-grounded gap:
{{
  "theme_label": "3-6 word technical theme that describes this cluster",
  "gaps": [
    {{
      "gap_title": "Precise technical title, max 12 words",
      "description": "Exactly 5 sentences following the structure above. Each sentence ends with [N].",
      "what_fails": "One sentence naming the exact mechanism, algorithm, or assumption that fails.",
      "why_it_exists": "One sentence giving the root cause (data scarcity / architectural limit / evaluation blind-spot / theoretical constraint).",
      "missing_piece": "One sentence: the specific artefact (dataset / metric / model / proof) that does not yet exist.",
      "pattern_detected": "One short phrase: the overarching trend seen across these papers.",
      "proposed_direction": "One full sentence: a concrete experiment, system, or study that would close this gap.",
      "confidence_score": 0.0
    }}
  ]
}}
EVERY field must be a non-empty English sentence. NEVER output null, undefined, N/A, or leave any field empty.
confidence_score: float 0.0–1.0 reflecting how strongly the evidence supports this gap."""


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
) -> tuple[list[SynthesisGap], str | None]:

    gap_serial = f"GAP-{cluster_id + 1:03d}"
    _all_papers = all_papers or cluster_papers

    confidence_score = compute_gap_score(cluster_papers, _all_papers)

    # Heuristic themes for prompt injection
    themes = extract_cluster_themes(cluster_papers)

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
        prompt = _gap_prompt(cluster_id, cluster_papers, topic, pattern_data, themes)

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
                "description": renumber_text(clean("description")),
                "what_fails": renumber_text(clean("what_fails")),
                "why_it_exists": renumber_text(clean("why_it_exists")),
                "missing_piece": renumber_text(clean("missing_piece")),
                "pattern_detected": clean("pattern_detected"),
                "proposed_direction": renumber_text(clean("proposed_direction")),
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

    # Process all clusters with the LLM for maximum gap coverage
    max_llm_clusters = 15

    # Use a semaphore to limit concurrent LLM calls to prevent aggressive rate limits
    sem = asyncio.Semaphore(3)

    async def _process_cluster(i: int, cid: int, cprs: list[dict]):
        force_heuristic = i >= max_llm_clusters
        async with sem:
            try:
                # Add a small stagger to prevent sending all requests at the exact same millisecond
                if not force_heuristic and i > 0:
                    await asyncio.sleep(0.5 * min(i, 5))
                return await generate_gaps_for_cluster(
                    cid, cprs, topic, pattern, _all, force_heuristic=force_heuristic
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
