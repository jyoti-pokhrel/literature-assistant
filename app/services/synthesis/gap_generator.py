from __future__ import annotations

import json
import logging
import os
import re
import math
import uuid
from pathlib import Path
from typing import List, Any

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent.parent.parent / ".env")

OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
MODEL_NAME: str = os.getenv("MODEL_NAME", "qwen/qwen-2.5-7b-instruct")

logger = logging.getLogger(__name__)

from app.schemas.synthesis import CitationRef, SynthesisGap


# Prompt helpers

def _build_cluster_context(cluster_papers: list[dict]) -> str:
    lines: list[str] = []
    for i, p in enumerate(cluster_papers[:8], 1):
        title = p.get("title", "Unknown")
        year = p.get("year", "?")
        abstract = (p.get("abstract") or "")[:400]
        limitations = "; ".join((p.get("normalized_limitations") or [])[:4])
        future_work = "; ".join((p.get("normalized_future_work") or [])[:4])
        methods = "; ".join((p.get("normalized_methods") or [])[:3])
        metrics = "; ".join((p.get("normalized_metrics") or [])[:3])
        
        lines.append(
            f"[{i}] {title} ({year})\n"
            f"    - Methods: {methods or 'N/A'}\n"
            f"    - Metrics: {metrics or 'N/A'}\n"
            f"    - Abstract: {abstract}...\n"
            f"    - Limitations: {limitations or 'N/A'}\n"
            f"    - Future work: {future_work or 'N/A'}"
        )
    return "\n\n".join(lines)


def _gap_prompt(cluster_id: int, cluster_papers: list[dict], topic: str, pattern: dict = {}) -> str:
    context = _build_cluster_context(cluster_papers)
    return f"""You are a Research Strategist. Analyze the following cluster of research papers on "{topic}" to identify a HIGH-PRECISION research gap.

### Global Literature Patterns (Across all clusters):
- Top Methods: {pattern.get('top_methods', [])}
- Top Limitations: {pattern.get('top_limitations', [])}
- Top Metrics: {pattern.get('top_metrics', [])}

### Cluster Context (Specific to this gap):
{context}

### Task:
Identify ONE specific research gap. A "Gap" is NOT just something missing; it is a point where existing literature [1] hits a wall, disagrees, or uses insufficient methods.

### Gap Categories to consider:
1. Methodological Stagnation: Approaches [1] and [2] use the same biased metric or inefficient architecture.
2. Empirical Blindspot: A specific real-world scenario or dataset type is missing across all papers.
3. Conflict/Divergence: Paper [1] claims X, but Paper [2] shows Y, and no one has reconciled them.

### Response Requirements:
- CITATION RIGOR: You MUST cite specific papers using numeric indices [1], [2] in the "description", "what_fails", and "missing_piece" fields.
- NO GENERALITIES: Avoid "more research is needed." Be technical, specific, and data-driven.
- PROPOSED DIRECTION: Suggest a unique, concrete next step. Avoid generic "combine X with Y" templates unless truly justified. Focus on specific technical novelties or paradigm shifts.
- PHRASING DIVERSITY: Do NOT use the same sentence structure or introductory phrases for every gap. Each proposal should feel distinct and tailored to the technical context of the cluster.
- NO PLACEHOLDERS: NEVER return the literal strings "undefined", "null", "N/A", or "unknown" for any field. If information is truly missing, provide a technical deduction or output an empty string "".

Return ONLY a JSON object:
{{
  "gap_title": "Precise technical title",
  "description": "4-6 sentence analysis of the gap, citing relevant papers using [1] notation",
  "what_fails": "Why current methods in [1] fail or reach a limit",
  "why_it_exists": "The root cause (e.g. data scarcity, compute limits, theoretical oversight)",
  "missing_piece": "The specific technical component or study currently missing, citing [1] if relevant",
  "pattern_detected": "The high-level trend (e.g. 'Over-reliance on synthetic data' or 'Evaluation bias')",
  "proposed_direction": "A concrete, actionable research project or technical approach",
  "confidence_score": 0.0
}}
Confidence should reflect the strength of evidence in the provided abstracts. Use a float 0.0-1.0."""


#OpenRouter call

def _call_openrouter(prompt: str) -> str:
    """Synchronous HTTP call to OpenRouter chat completion."""
    import urllib.request

    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not set in .env")

    payload = json.dumps(
        {
            "model": MODEL_NAME,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 600,
        }
    ).encode()

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


def _extract_json(text: str) -> dict:

    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find first {...} block
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def _make_citations(papers: list[dict], cited_indices: set[int] | None = None) -> list[CitationRef]:
    refs: list[CitationRef] = []
    # Use only cited papers if indices provided, otherwise fallback to first 5
    if cited_indices:
        for idx in sorted(list(cited_indices)):
            if 0 <= idx < len(papers):
                p = papers[idx]
                evidence = (p.get("normalized_limitations") or [])[:2] + (p.get("normalized_future_work") or [])[:2]
                refs.append(
                    CitationRef(
                        paper_id=p.get("paper_id"),
                        title=p.get("title", "Unknown"),
                        year=p.get("year"),
                        source=p.get("source"),
                        venue=p.get("venue") or "Unknown Venue",
                        citation_count=p.get("citation_count") or 0,
                        url=p.get("url"),
                        extracted_evidence=evidence
                    )
                )
    else:
        for p in papers[:5]:
            evidence = (p.get("normalized_limitations") or [])[:2] + (p.get("normalized_future_work") or [])[:2]
            refs.append(
                CitationRef(
                    paper_id=p.get("paper_id"),
                    title=p.get("title", "Unknown"),
                    year=p.get("year"),
                    source=p.get("source"),
                    venue=p.get("venue") or "Unknown Venue",
                    citation_count=p.get("citation_count") or 0,
                    url=p.get("url"),
                    extracted_evidence=evidence
                )
            )
    return refs


from app.services.analysis.scoring import (
    score_support, score_severity, score_actionability, 
    score_novelty, score_citation_confidence, compute_overall_score
)

def _score_from_evidence(cluster_papers: list[dict], cluster_id: int = -1) -> float:
    """Compute a high-fidelity confidence score using the core scoring modules."""
    if not cluster_papers:
        return 0.0
        
    # Prepare dummy evidence dict for scoring modules
    evidence = {
        "recurring_limitations": [l for p in cluster_papers for l in p.get("normalized_limitations", [])],
        "recurring_future_work": [f for p in cluster_papers for f in p.get("normalized_future_work", [])],
        "dominant_assumptions": [a for p in cluster_papers for a in p.get("normalized_assumptions", [])],
        "missing_metrics": [m for p in cluster_papers for m in p.get("normalized_metrics", [])],
    }
    
    # Determine category based on content
    category = "methodology"
    if any(term in str(evidence).lower() for term in ["deployment", "safe", "robust", "real-world"]):
        category = "deployment"
    
    # Calculate sub-scores
    s_support = score_support(cluster_papers)
    s_severity = score_severity(category, evidence)
    s_action = score_actionability(category, evidence)
    s_novelty = score_novelty(cluster_papers)
    s_cite = score_citation_confidence(cluster_papers)
    
    # Combine and normalize
    raw_score = compute_overall_score(s_support, s_severity, s_action, s_novelty, s_cite)
    
    # Sigmoid-like normalization to 0.0 - 0.99 range
    confidence = 1 / (1 + math.exp(-0.5 * (raw_score - 2.5)))
    return round(min(0.99, max(0.1, confidence)), 2)


# Public API

def generate_gaps_for_cluster(
    cluster_id: int,
    cluster_papers: list[dict],
    topic: str,
    pattern: Any = {},
) -> SynthesisGap:
    
    gap_serial = f"GAP-{cluster_id + 1:03d}"
    fallback_score = _score_from_evidence(cluster_papers)
    paper_ids = [p.get("paper_id") or p.get("title", "") for p in cluster_papers]
    citations = _make_citations(cluster_papers)
    pattern_data = pattern if isinstance(pattern, dict) else (pattern.model_dump() if hasattr(pattern, 'model_dump') else {})

    try:
        prompt = _gap_prompt(cluster_id, cluster_papers, topic, pattern_data)
        raw = _call_openrouter(prompt)
        data = _extract_json(raw)

        # Citation Awareness: Extract cited indices from text fields
        text_content = f"{data.get('description', '')} {data.get('what_fails', '')} {data.get('missing_piece', '')}"
        cited_indices = set()
        for match in re.finditer(r"\[(\d+)\]", text_content):
            try:
                idx = int(match.group(1)) - 1 # 1-based to 0-based
                if 0 <= idx < len(cluster_papers):
                    cited_indices.add(idx)
            except ValueError:
                continue
        
        # If no citations found in text, use all papers in cluster as fallback
        citations = _make_citations(cluster_papers, cited_indices if cited_indices else None)
        cited_paper_ids = []
        if cited_indices:
            cited_paper_ids = [cluster_papers[i].get("paper_id") or cluster_papers[i].get("title", "") for i in cited_indices]
        else:
            cited_paper_ids = paper_ids[:5] # Fallback to first 5

        def _clean_val(v, default=""):
            if v is None: return default
            
            # Convert to string and aggressively strip out standalone "undefined" occurrences
            s = str(v)
            s = re.sub(r'(?i)\bundefined\b', '', s)
            
            s = s.strip()
            if not s: return default
            
            lower_s = s.lower()
            # Centralized junk patterns matching app/schemas/synthesis.py
            junk = {
                "null", "[object object]", "none", "n/a", 
                "unknown", "string", "empty", "all", "any", "javascript:void(0)"
            }
            
            # Direct match
            if lower_s in junk:
                return default
            
            # Cleaned match
            clean = re.sub(r'[^a-z0-9]', '', lower_s)
            if clean in junk:
                return default
                
            # Leak detection in short sentences
            if len(s) < 80 and any(j in lower_s for j in ["null", "[object"]):
                return default
                
            return s

        # Always calculate our own confidence score to ensure it's data-driven and unique
        final_score = _score_from_evidence(cluster_papers, cluster_id)

        return SynthesisGap(
            gap_id=gap_serial,
            gap_title=_clean_val(data.get("gap_title", f"Research gap in cluster {cluster_id}")),
            description=_clean_val(data.get("description", "")),
            what_fails=_clean_val(data.get("what_fails", "")),
            why_it_exists=_clean_val(data.get("why_it_exists", "")),
            missing_piece=_clean_val(data.get("missing_piece", "")),
            pattern_detected=_clean_val(data.get("pattern_detected", "")),
            proposed_direction=_clean_val(data.get("proposed_direction", "")),
            confidence_score=final_score,
            cluster_id=cluster_id,
            supporting_papers=cited_paper_ids,
            citations=citations,
        )
    except Exception as exc:
        logger.warning("LLM gap generation failed for cluster %d: %s", cluster_id, exc)
        # Return a heuristic gap derived from existing analysis services
        return _heuristic_gap(cluster_id, cluster_papers, topic, gap_serial, fallback_score, citations, paper_ids)


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

    return SynthesisGap(
        gap_id=gap_id,
        gap_title=f"Unresolved gap in {topic}: {lim_text[:60]}",
        description=(
            f"Across {len(papers)} papers in this cluster, a recurring limitation is '{lim_text}'. "
            f"Authors frequently cite '{fw_text}' as open future work."
        ),
        what_fails=lim_text,
        why_it_exists="This limitation appears repeatedly without resolution across the surveyed literature.",
        missing_piece=fw_text,
        pattern_detected=f"Recurring limitation: {lim_text}",
        proposed_direction=f"Address '{lim_text}' through a targeted study focused on '{fw_text}'.",
        confidence_score=score,
        cluster_id=cluster_id,
        supporting_papers=paper_ids,
        citations=citations,
    )


def generate_all_gaps(
    papers: list[dict],
    labels: "list[int]",
    topic: str,
    pattern: Any = {},
    top_k: int = 5,
) -> list[SynthesisGap]:
 
    from collections import defaultdict

    cluster_map: dict[int, list[dict]] = defaultdict(list)
    for paper, label in zip(papers, labels):
        if label != -1:
            cluster_map[int(label)].append(paper)

    # If all noise, treat the whole set as one cluster
    if not cluster_map:
        cluster_map[0] = papers

    gaps: list[SynthesisGap] = []
    for cluster_id, cluster_papers in cluster_map.items():
        gap = generate_gaps_for_cluster(cluster_id, cluster_papers, topic, pattern)
        gaps.append(gap)

    return sorted(gaps, key=lambda g: g.confidence_score, reverse=True)[:top_k]
