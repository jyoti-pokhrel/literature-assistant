from __future__ import annotations

import json
import logging
import os
import re
import math
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent.parent.parent / ".env")

# Model chain
PRIMARY_MODEL: str = os.getenv("SYNTHESIS_MODEL_PRIMARY")
if not PRIMARY_MODEL:
    raise RuntimeError("SYNTHESIS_MODEL_PRIMARY is not set in .env")

FALLBACK_MODEL: str = os.getenv("SYNTHESIS_MODEL_FALLBACK")
if not FALLBACK_MODEL:
    raise RuntimeError("SYNTHESIS_MODEL_FALLBACK is not set in .env")
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
import os

MODEL_NAME: str = os.getenv("MODEL_NAME", "qwen/qwen-2.5-7b-instruct")

LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "remote").lower()

LOCAL_LLM_URL: str = os.getenv(
    "LOCAL_LLM_URL",
    "http://127.0.0.1:11434/api/generate"
)

LOCAL_MODEL_NAME: str = os.getenv(
    "LOCAL_MODEL_NAME",
    os.getenv("MODEL_NAME", "qwen2.5:7b")
)

logger = logging.getLogger(__name__)

from app.schemas.synthesis import CitationRef, SynthesisGap
from app.services.synthesis.gap_scorer import compute_gap_score
from app.services.synthesis.pattern_analysis import extract_cluster_themes
from app.services.synthesis.citation_validation import validate_gap_citations


#Prompt helpers

def _build_cluster_context(cluster_papers: list[dict]) -> str:
    lines: list[str] = []
    for i, p in enumerate(cluster_papers[:8], 1):
        title = p.get("title", "Unknown")
        year = p.get("year", "?")
        abstract = (p.get("abstract") or "")[:1000]
        limitations = "; ".join((p.get("normalized_limitations") or [])[:8])
        future_work = "; ".join((p.get("normalized_future_work") or [])[:8])
        methods = "; ".join((p.get("normalized_methods") or p.get("normalized_method") or [p.get("method")] if p.get("method") else [])[:5])
        metrics = "; ".join((p.get("normalized_metrics") or [])[:5])

        lines.append(
            f"[{i}] {title} ({year})\n"
            f"    - Methods: {methods or 'N/A'}\n"
            f"    - Metrics: {metrics or 'N/A'}\n"
            f"    - Abstract: {abstract}...\n"
            f"    - Limitations: {limitations or 'N/A'}\n"
            f"    - Future work: {future_work or 'N/A'}"
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

    top_methods = ", ".join(str(m) for m in (pattern.get("top_methods") or [])[:5]) or "N/A"
    top_limitations = ", ".join(str(l) for l in (pattern.get("top_limitations") or [])[:5]) or "N/A"
    top_metrics = ", ".join(str(m) for m in (pattern.get("top_metrics") or [])[:5]) or "N/A"

    cluster_lims = ", ".join(themes.get("top_limitations") or []) or "unspecified"
    cluster_fw = ", ".join(themes.get("top_future_work") or []) or "unspecified"
    theme_label = themes.get("theme_label", "unspecified")

    return f"""You are a Research Strategist. Analyze the following cluster of research papers on "{topic}" to identify a HIGH-PRECISION research gap.

### Global Literature Patterns (Across all clusters):
- Top Methods: {top_methods}
- Top Limitations: {top_limitations}
- Top Metrics: {top_metrics}

### This Cluster's Dominant Theme: "{theme_label}"
- Recurring limitations in this cluster: {cluster_lims}
- Recurring future-work directions: {cluster_fw}
- Papers in cluster: {themes.get("paper_count", len(cluster_papers))}

### Cluster Context (Full paper details):
{context}

### Task:
Identify ONE specific, actionable research gap grounded in the cluster's dominant theme above. A "Gap" is NOT just something missing; it is a concrete point where existing literature [1] hits a wall, disagrees, or uses insufficient methods.

### Gap Categories to consider:
1. Methodological Stagnation: Approaches [1] and [2] use the same biased metric or inefficient architecture.
2. Empirical Blindspot: A specific real-world scenario or dataset type is missing across all papers.
3. Conflict/Divergence: Paper [1] claims X, but Paper [2] shows Y, and no one has reconciled them.

### Response Requirements:
- NO MULTI-CITATIONS: NEVER group citations. Use exactly ONE citation number per claim. WRONG: "[1, 2]", "[1], [2]", "[1] and [2]".
- NO PROSE CITATIONS: NEVER start a sentence with "Paper [N]", "Study [N]", "Authors in [N]", or "[N] highlights". The citation MUST ONLY appear at the very end of the sentence.
- GROUNDED CITATIONS: Every claim with a citation [N] MUST be a high-fidelity, non-misleading representation of the specific methods, results, or limitations provided in the "Cluster Context". Do not generalize or guess.
- STRICT CITATION FORMAT: The citation bracket MUST attach directly to the LAST WORD of the sentence, with ZERO spaces, before the full stop. Pattern: word[N]. — NOT word [N]. NOT word[N] . NOT [N] word.
- NO GENERALITIES: Be technical, specific, and data-driven. Cite specific limitations or methods.
- PROPOSED DIRECTION: Suggest a unique, concrete technical approach or paradigm shift.
- PHRASING DIVERSITY: Each gap must feel distinct; avoid generic templates.
- NO PLACEHOLDERS: NEVER return "undefined", "null", "N/A", or "unknown" for any field.

Return ONLY a valid JSON object with exactly these keys:
{{
  "gap_title": "Precise technical title (max 12 words)",
  "description": "4-10 sentence analysis citing relevant papers using [1] notation. Every cited claim must be factually accurate and non-misleading relative to the provided context (methods, results, limitations), maintaining a professional, analytical tone (not verbatim).",
  "what_fails": "Why current methods in [1] fail or reach a limit",
  "why_it_exists": "The root cause (e.g. data scarcity, compute limits, theoretical oversight)",
  "missing_piece": "The specific technical component or study currently missing, citing [1] if relevant",
  "pattern_detected": "The high-level trend (e.g. 'Over-reliance on synthetic data')",
  "proposed_direction": "A concrete, actionable research project or technical approach (must be a full English sentence, no placeholders)",
  "confidence_score": 0.0
}}
IMPORTANT: Every field MUST be a complete English sentence. NEVER output "undefined", "null", "N/A", or leave any field empty.
Confidence should reflect evidence strength in the cluster. Use a float 0.0-1.0."""


#OpenRouter call

def _call_openrouter(prompt: str, model: str) -> str:
    """Synchronous HTTP call to OpenRouter chat completion."""
    import urllib.request

    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not set in .env")

    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 900,
    }).encode()

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://research-agent.local",
            "X-Title": "Research Agent Synthesis",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = json.loads(resp.read().decode())
    return raw["choices"][0]["message"]["content"].strip()


def _call_local_model(prompt: str) -> str:
    """Call a local Ollama-compatible generation endpoint."""
    import urllib.request

    payload = json.dumps(
        {
            "model": LOCAL_MODEL_NAME,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 700},
        }
    ).encode()
    req = urllib.request.Request(
        LOCAL_LLM_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        raw = json.loads(resp.read().decode())
    return str(raw.get("response") or raw.get("content") or "").strip()


def _call_llm(prompt: str) -> str:
    if LLM_PROVIDER == "local" or (not OPENROUTER_API_KEY and LOCAL_LLM_URL):
        return _call_local_model(prompt)
    return _call_openrouter(prompt)


def _extract_json(text: str) -> dict:
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
    s = re.sub(r'(?i)\bundefined\b', '', str(v)).strip()
    if not s:
        return default
    lower_s = s.lower()
    junk = {
        "null", "[object object]", "none", "n/a",
        "unknown", "string", "empty", "all", "any", "javascript:void(0)"
    }
    if lower_s in junk:
        return default
    clean = re.sub(r'[^a-z0-9]', '', lower_s)
    if clean in junk:
        return default
    if len(s) < 80 and any(j in lower_s for j in ["null", "[object"]):
        return default
    return s

def _strip_invalid_citations(text: str, n_papers: int) -> str:
    """Remove [n] markers where n is out of bounds for the paper list."""
    def _replace(m: re.Match) -> str:
        try:
            idx = int(m.group(1)) - 1
            return m.group(0) if 0 <= idx < n_papers else ""
        except (ValueError, TypeError):
            return ""
    return re.sub(r'\[(\d+)\]', _replace, text).strip()


def _collapse_multi_citations(text: str, n_papers: int) -> str:
    """Convert grouped citations [1, 3, 4, 5] or [1], [2] → [1]."""
    def _first_valid(m: re.Match) -> str:
        nums = re.findall(r'\d+', m.group(0))
        for num in nums:
            idx = int(num) - 1
            if 0 <= idx < n_papers:
                return f'[{num}]'
        return ''
    
    # 1. Match [1, 2, 3] or [1,2,3]
    text = re.sub(r'\[\d+(?:\s*,\s*\d+)+\]', _first_valid, text)
    # 2. Match [1], [2], and [3] or [1], [2], [3]
    text = re.sub(r'\[\d+\](?:\s*(?:,|and|&)\s*\[\d+\])+', _first_valid, text)
    # 3. Strip "Paper [N]" and "Papers [N]" etc.
    text = re.sub(r'(?i)\bPapers?\s*\[\d+\]\b', '', text)
    text = re.sub(r'(?i)\bStudies\s*\[\d+\]\b', '', text)
    text = re.sub(r'(?i)\bAuthors\s+in\s+\[\d+\]\b', '', text)
    
    return _strip_invalid_citations(text, n_papers)


def _fix_citation_spacing(text: str) -> str:
    """Remove space artifacts around citation markers.

    'word [n].'  → 'word[n].'
    'word[n] .'  → 'word[n].'
    'word [n] .' → 'word[n].'
    """
    text = re.sub(r'(\w)\s+\[(\d+)\]', r'\1[\2]', text)
    text = re.sub(r'\[(\d+)\]\s+([.,;!?])', r'[\1]\2', text)
    return text.strip()


def _make_citations(
    papers: list[dict],
    cited_indices: set[int] | None = None,
) -> list[CitationRef]:
    refs: list[CitationRef] = []
    source_papers = (
        [papers[i] for i in sorted(cited_indices) if 0 <= i < len(papers)]
        if cited_indices
        else papers[:5]
    )
    for p in source_papers:
        evidence = (p.get("normalized_limitations") or [])[:2] + (p.get("normalized_future_work") or [])[:2]
        refs.append(CitationRef(
            paper_id=p.get("paper_id"),
            title=p.get("title", "Unknown"),
            year=p.get("year"),
            source=p.get("source"),
            venue=p.get("venue") or "Unknown Venue",
            citation_count=p.get("citation_count") or 0,
            url=p.get("url"),
            extracted_evidence=evidence,
        ))
    return refs


import re
import math
from difflib import SequenceMatcher

from app.services.analysis.scoring import (
    score_support, score_severity, score_actionability, 
    score_novelty, score_citation_confidence, compute_overall_score,
    build_gap_score_breakdown,
)


def _extract_and_verify_citations(text: str, papers: list[dict]) -> set[int]:
    valid_indices: set[int] = set()
    found_strict = False

    for match in re.finditer(r'([^.!?\n]+)\s*\[(\d+)\]', text):
        found_strict = True

        quote = match.group(1).lower().strip(' "\'')
        try:
            idx = int(match.group(2)) - 1
        except ValueError:
            continue

        if 0 <= idx < len(papers):
            paper = papers[idx]

            title = paper.get("title", "").lower()

            # fuzzy validation between quote and paper title
            similarity = SequenceMatcher(None, quote, title).ratio()

            if similarity > 0.35:
                valid_indices.add(idx)

    return valid_indices



def _build_evidence(cluster_papers: list[dict]) -> dict:
    return {
        "recurring_limitations": [l for p in cluster_papers for l in p.get("normalized_limitations", [])],
        "recurring_future_work": [f for p in cluster_papers for f in p.get("normalized_future_work", [])],
        "dominant_assumptions": [a for p in cluster_papers for a in p.get("normalized_assumptions", [])],
        "missing_metrics": [m for p in cluster_papers for m in p.get("normalized_metrics", [])],
        "missing_datasets": [d for p in cluster_papers for d in p.get("normalized_datasets", [])],
        "weak_baselines": [b for p in cluster_papers for b in p.get("normalized_baselines", [])],
    }


def _gap_category(evidence: dict) -> str:
    evidence_text = str(evidence).lower()

    if any(term in evidence_text for term in ["metric", "baseline", "evaluation", "reward"]):
        return "evaluation"

    if any(term in evidence_text for term in ["deployment", "safe", "robust", "real-world"]):
        return "deployment"

    return "methodology"


def _score_from_evidence(cluster_papers: list[dict], cluster_id: int = -1, text: str = "") -> float:
    if not cluster_papers:
        return 0.0

    evidence = _build_evidence(cluster_papers)
    category = _gap_category(evidence)

    # Core scoring signals
    s_support = score_support(cluster_papers)
    s_severity = score_severity(category, evidence)
    s_action = score_actionability(category, evidence)
    s_novelty = score_novelty(cluster_papers)

    valid_citations = _extract_and_verify_citations(text, cluster_papers)
    citation_signal = len(valid_citations) / max(1, len(cluster_papers))

    s_cite = score_citation_confidence(cluster_papers)

    raw_score = compute_overall_score(
        s_support,
        s_severity,
        s_action,
        s_novelty,
        s_cite * (0.7 + 0.3 * citation_signal)
    )

    confidence = 1 / (1 + math.exp(-0.5 * (raw_score - 2.5)))
    return round(min(0.99, max(0.1, confidence)), 2)
        if len(quote) < 10: 
            if 0 <= idx < len(papers):
                valid_indices.add(idx)
            continue

        def _get_paper_text(p: dict) -> str:
            return (
                str(p.get("title", "")) + " " +
                str(p.get("abstract", "")) + " " +
                " ".join(p.get("normalized_limitations", [])) + " " +
                " ".join(p.get("normalized_future_work", []))
            ).lower()

        if 0 <= idx < len(papers):
            paper_text = _get_paper_text(papers[idx])
            # Check exact match or highly similar substring
            if quote in paper_text or SequenceMatcher(None, quote, paper_text).find_longest_match(0, len(quote), 0, len(paper_text)).size > len(quote) * 0.8:
                valid_indices.add(idx)
                continue

        # If it wasn't in the cited paper, check if the LLM just hallucinated the number
        for alt_idx, alt_paper in enumerate(papers):
            if alt_idx == idx:
                continue
            alt_text = _get_paper_text(alt_paper)
            if quote in alt_text or SequenceMatcher(None, quote, alt_text).find_longest_match(0, len(quote), 0, len(alt_text)).size > len(quote) * 0.8:
                valid_indices.add(alt_idx)
                break

    # 2. Fallback: If no strict format was found at all, grab loose [idx]
    if not found_strict:
        for match in re.finditer(r"\[(\d+)\]", text):
            try:
                idx = int(match.group(1)) - 1
                if 0 <= idx < len(papers):
                    valid_indices.add(idx)
            except ValueError:
                continue

    return valid_indices


#Public API

def generate_gaps_for_cluster(
    cluster_id: int,
    cluster_papers: list[dict],
    topic: str,
    pattern: Any = {},
    all_papers: list[dict] | None = None,
) -> SynthesisGap:

    gap_serial = f"GAP-{cluster_id + 1:03d}"
    _all_papers = all_papers or cluster_papers

    # Pre-compute spec-exact confidence score
    confidence_score = compute_gap_score(cluster_papers, _all_papers)

    # Extract deduped per-cluster themes for prompt injection
    themes = extract_cluster_themes(cluster_papers)

    paper_ids = [p.get("paper_id") or p.get("title", "") for p in cluster_papers]
    pattern_data = (
        pattern if isinstance(pattern, dict)
        else (pattern.model_dump() if hasattr(pattern, "model_dump") else {})
    )

<<try:
    prompt = _gap_prompt(cluster_id, cluster_papers, topic, pattern_data)


    raw = None
    last_exc = None

    for model_name in [PRIMARY_MODEL, FALLBACK_MODEL]:
        try:
            raw = _call_openrouter(prompt, model_name)
            break
        except Exception as exc:
            last_exc = exc
            logger.warning("Model %s failed: %s", model_name, exc)

    if raw is None:
        raise RuntimeError(f"All LLM models failed: {last_exc}")

    data = _extract_json(raw)


    text_content = f"{data.get('description','')} {data.get('what_fails','')} {data.get('missing_piece','')}"

    cited_indices = _extract_and_verify_citations(text_content, cluster_papers)

    # fallback: ensure minimum support
    if len(cited_indices) < 2:
        cited_indices = set(range(min(2, len(cluster_papers))))

    citations = _make_citations(cluster_papers)

    cited_paper_ids = [
        cluster_papers[i].get("paper_id") or cluster_papers[i].get("title", "")
        for i in sorted(cited_indices)
    ]


    def clean(key, default=""):
        return _clean_val(data.get(key)) or default

    gap_fields = {
        "gap_title": clean("gap_title", f"Research gap in cluster {cluster_id}"),
        "description": clean("description"),
        "what_fails": clean("what_fails"),
        "why_it_exists": clean("why_it_exists"),
        "missing_piece": clean("missing_piece"),
        "pattern_detected": clean("pattern_detected"),
        "proposed_direction": clean("proposed_direction"),
    }


    final_score = _score_from_evidence(cluster_papers, cluster_id)

    evidence = _build_evidence(cluster_papers)
    score_breakdown = build_gap_score_breakdown(
        cluster_papers,
        evidence,
        _gap_category(evidence)
    )

    citation_validation = validate_gap_citations(gap_fields, citations)


    return SynthesisGap(
        gap_id=gap_serial,
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
        citation_validation=citation_validation,
    )

except Exception as exc:
    logger.warning("LLM gap generation failed for cluster %d: %s", cluster_id, exc)

    return _heuristic_gap(
        cluster_id,
        cluster_papers,
        topic,
        gap_serial,
        confidence_score,
        _make_citations(cluster_papers),
        paper_ids,
    )


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

    lim_counter: Counter[str] = Counter()
    fw_counter: Counter[str] = Counter()
    for p in papers:
        for lim in p.get("normalized_limitations", []):
            lim_counter[lim] += 1
        for fw in p.get("normalized_future_work", []):
            fw_counter[fw] += 1

    top_lim = lim_counter.most_common(1)
    top_fw = fw_counter.most_common(1)
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
        score_breakdown=build_gap_score_breakdown(papers, evidence, _gap_category(evidence)),
        citation_validation=validate_gap_citations(gap_fields, citations),
    )

def generate_all_gaps(
    papers: list[dict],
    labels: list[int],
    topic: str,
    pattern: Any = {},
    top_k: int = 5,
    all_papers: list[dict] | None = None,
) -> list[SynthesisGap]:
    from collections import defaultdict
    import concurrent.futures

    _all = all_papers or papers
    cluster_map: dict[int, list[dict]] = defaultdict(list)
    for paper, label in zip(papers, labels):
        if label != -1:
            cluster_map[int(label)].append(paper)

    # If all noise, treat entire corpus as one cluster
    if not cluster_map:
        cluster_map[0] = papers

    gaps: list[SynthesisGap] = []
    
    def _generate(cluster_id, cluster_papers):
        return generate_gaps_for_cluster(cluster_id, cluster_papers, topic, pattern, _all)

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [
            executor.submit(_generate, cluster_id, cluster_papers)
            for cluster_id, cluster_papers in cluster_map.items()
        ]
        for future in concurrent.futures.as_completed(futures):
            try:
                gaps.append(future.result())
            except Exception as e:
                logger.error(f"Error generating gaps for cluster: {e}")

    return sorted(gaps, key=lambda g: g.confidence_score, reverse=True)[:top_k]
