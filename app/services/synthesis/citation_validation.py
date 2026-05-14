from __future__ import annotations

import re
from typing import Any


#Cosine similarity

def _cosine_similarity(vec_a, vec_b) -> float:
    import numpy as np
    norm = float(np.linalg.norm(vec_a) * np.linalg.norm(vec_b))
    return float(np.dot(vec_a, vec_b) / norm) if norm > 1e-9 else 0.0


def _embed_batch(texts: list[str]):

    if not texts:
        return None
    try:
        import os
        from app.services.synthesis.embeddings import get_model
        model = get_model(os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"))
        return model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
    except Exception:
        return None


#Paper context builder

def _paper_context(citation: Any) -> str:

    title = getattr(citation, "title", "") or ""
    evidence = getattr(citation, "extracted_evidence", None)
    if evidence is None and isinstance(citation, dict):
        evidence = citation.get("extracted_evidence", [])
    ev_text = ". ".join(str(e) for e in (evidence or []) if e)
    return f"{title}. {ev_text}".strip(" .")


#Sentence → citation-number map

def _build_sent_citation_map(text: str) -> dict[str, list[int]]:
   
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    result: dict[str, list[int]] = {}
    for sent in sentences:
        ns = [int(m) for m in re.findall(r"\[(\d+)\]", sent)]
        if ns:
            clean = re.sub(r"\[\d+\]", "", sent).strip()
            if len(clean) > 15:          # ignore very short fragments
                result[clean] = ns
    return result


def validate_gap_against_supported_papers(
    gap_fields: dict[str, Any],
    cluster_papers: list[dict],
) -> dict[str, Any]:
    """
    Cross-references a gap against all papers in the cluster (supported papers).
    Includes abstracts and extracted evidence for a deeper check.
    """
    if not cluster_papers:
        return {"status": "unvalidated", "reason": "No papers available for validation."}

    # 1. Semantic check
    # Include title for better context matching
    target_text = f"{gap_fields.get('gap_title', '')}: {gap_fields.get('what_fails', '')} {gap_fields.get('missing_piece', '')}".strip()
    if len(target_text) < 20:
        return {"status": "unvalidated", "reason": "Gap description too short for semantic validation."}

    # Prepare cluster paper contexts (titles + abstracts + evidence)
    paper_contexts = []
    for p in cluster_papers:
        title = p.get('title', '')
        text = f"{p.get('abstract', '') or p.get('contribution', '')}"
        ev = p.get('extracted_evidence', [])
        if ev:
            text += " " + " ".join(str(e) for e in ev if e)
        paper_contexts.append(f"{title}. {text}")
    
    all_texts = [target_text] + paper_contexts
    vecs = _embed_batch(all_texts)
    if vecs is None:
        return {"status": "error", "reason": "Embedding service failed."}

    target_vec = vecs[0]
    paper_vecs = vecs[1:]
    
    matches: list[dict] = []
    for i, p_vec in enumerate(paper_vecs):
        sim = _cosine_similarity(target_vec, p_vec)
        # Check if the paper's "contribution" area matches our "gap"
        # 0.60 is a safer threshold for semantic overlap in technical text
        if sim > 0.60: 
            matches.append({
                "paper_id": cluster_papers[i].get("paper_id"),
                "title": cluster_papers[i].get("title"),
                "similarity": round(sim, 3)
            })

    if matches:
        matches.sort(key=lambda x: x["similarity"], reverse=True)
        return {
            "status": "potentially_addressed",
            "reason": f"Found {len(matches)} papers in the cluster that may already address this gap.",
            "conflicting_papers": matches[:3]
        }

    return {
        "status": "validated",
        "reason": f"Gap confirmed as unique against {len(cluster_papers)} cluster papers."
    }

async def verify_gap_with_llm(
    gap_fields: dict[str, Any],
    citations: list[Any],
    llm_client: Any,
) -> dict[str, Any]:
    """
    Uses the LLM to perform a high-fidelity check of the gap against cited evidence.
    """
    if not citations or not llm_client:
        return {"status": "unvalidated", "reason": "Insufficient data for LLM verification."}

    # Prepare evidence context
    evidence_text = ""
    for i, cit in enumerate(citations):
        context = _paper_context(cit)
        evidence_text += f"[{i+1}] {context}\n\n"

    prompt = f"""
Validate the following research gap against the provided evidence from cited papers.

RESEARCH GAP:
Title: {gap_fields.get('gap_title')}
Failure: {gap_fields.get('what_fails')}
Missing Piece: {gap_fields.get('missing_piece')}

EVIDENCE FROM CITED PAPERS:
{evidence_text}

TASK:
1. Check if the "Failure" and "Missing Piece" are explicitly or implicitly supported by the evidence.
2. Check if any cited paper actually SOLVES the "Missing Piece" (which would make the gap invalid).
3. Assign a final status: "Validated", "Hallucinated", or "Weakly Supported".

Return JSON only:
{{
  "status": "Validated" | "Hallucinated" | "Weakly Supported",
  "reason": "Brief explanation",
  "confidence": 0.0 to 1.0
}}
"""
    try:
        response = await llm_client.generate(prompt, response_format={"type": "json_object"})
        import json
        data = json.loads(response)
        return {
            "status": data.get("status", "Unknown").lower(),
            "reason": data.get("reason", "No reason provided."),
            "llm_confidence": data.get("confidence", 0.5)
        }
    except Exception as exc:
        return {"status": "error", "reason": f"LLM verification failed: {exc}"}


#Semantic grounding check

# Cosine similarity thresholds
_HALLUCINATION_THRESHOLD  = 0.25   # below → almost certainly hallucinated (e.g. CNN vs ViT scores ~0.24)
_WEAK_SUPPORT_THRESHOLD   = 0.40   # below → weakly supported


def _compute_grounding(
    gap_text: str,
    citations: list[Any],
) -> dict[int, float]:

    sent_map = _build_sent_citation_map(gap_text)
    if not sent_map or not citations:
        return {}

    # Collect (claim_sentence, citation_index_1based) pairs
    pairs: list[tuple[str, int]] = []
    for sent, ns in sent_map.items():
        for n in ns:
            if 1 <= n <= len(citations):
                pairs.append((sent, n))

    if not pairs:
        return {}

    claim_texts   = [p[0] for p in pairs]
    context_texts = [_paper_context(citations[p[1] - 1]) for p in pairs]

    # Single batch encode: [claims... , contexts...]
    all_texts = claim_texts + context_texts
    vecs = _embed_batch(all_texts)
    if vecs is None:
        return {}

    n_pairs      = len(pairs)
    claim_vecs   = vecs[:n_pairs]
    context_vecs = vecs[n_pairs:]

    # Average similarity per citation number (a citation may appear in multiple sentences)
    by_n: dict[int, list[float]] = {}
    for i, (_, n) in enumerate(pairs):
        sim = _cosine_similarity(claim_vecs[i], context_vecs[i])
        by_n.setdefault(n, []).append(sim)

    return {n: round(sum(s) / len(s), 3) for n, s in by_n.items()}


#Public API

def validate_gap_citations(
    gap_fields: dict[str, Any],
    citations: list[Any],
) -> dict[str, Any]:

    citation_count = len(citations)

    # Build full gap text
    gap_text = " ".join(
        str(gap_fields.get(f, "") or "")
        for f in ("description", "what_fails", "missing_piece",
                  "why_it_exists", "proposed_direction")
    )

    cited_numbers = sorted({int(m.group(1)) for m in re.finditer(r"\[(\d+)\]", gap_text)})
    invalid_refs  = [n for n in cited_numbers if n < 1 or n > citation_count]

    evidence_count = 0
    for cit in citations:
        ev = getattr(cit, "extracted_evidence", None)
        if ev is None and isinstance(cit, dict):
            ev = cit.get("extracted_evidence")
        evidence_count += len(ev or [])

    #Semantic grounding
    grounding_scores: dict[int, float] = _compute_grounding(gap_text, citations)

    hallucinated     = [n for n, s in grounding_scores.items() if s < _HALLUCINATION_THRESHOLD]
    weakly_supported = [n for n, s in grounding_scores.items()
                        if _HALLUCINATION_THRESHOLD <= s < _WEAK_SUPPORT_THRESHOLD]
    well_grounded    = [n for n, s in grounding_scores.items() if s >= _WEAK_SUPPORT_THRESHOLD]

    #Structural issues
    issues: list[str] = []
    if not cited_numbers:
        issues.append("No citation markers [N] found in gap text.")
    if invalid_refs:
        issues.append(
            f"Out-of-range citations: {', '.join(f'[{n}]' for n in invalid_refs)}."
        )
    if citation_count == 0:
        issues.append("No CitationRef objects attached.")
    if evidence_count == 0:
        issues.append("No extracted limitation/future-work evidence in citations.")
    if hallucinated:
        issues.append(
            f"Likely hallucinated (similarity < {_HALLUCINATION_THRESHOLD}): "
            f"{', '.join(f'[{n}]' for n in hallucinated)}. "
            "The cited paper's content does not match the claim."
        )

    #Overall status
    if hallucinated:
        status = "hallucinated"
    elif issues:
        status = "needs_review"
    elif weakly_supported and not well_grounded:
        status = "weakly_supported"
    else:
        status = "grounded"

    # Generate reasoning summary
    if status == "grounded":
        reasoning = f"The evidence strongly supports this gap across {citation_count} papers, with {evidence_count} specific evidence snippets extracted."
    elif status == "weakly_supported":
        reasoning = f"The gap is partially supported by {citation_count} papers, but some claims have low semantic alignment with the source text. Reviewing the '{weakly_supported}' citations is recommended."
    else:
        reasoning = " ".join(issues) if issues else "The validation engine identifies several gaps between the claim and the cited evidence."

    return {
        # Core flags
        "is_grounded":   status in ("grounded", "weakly_supported"),
        "status":        status,
        "reasoning":     reasoning,
        # Structural counts
        "cited_marker_count":     len(cited_numbers),
        "supporting_paper_count": citation_count,
        "evidence_snippet_count": evidence_count,
        "invalid_references":     invalid_refs,
        # Semantic grounding
        "grounding_scores":           grounding_scores,    # {N: cosine_sim}
        "hallucinated_citations":     hallucinated,        # [N, ...] sim < 0.22
        "weakly_supported_citations": weakly_supported,    # [N, ...] sim 0.22–0.38
        "well_grounded_citations":    well_grounded,       # [N, ...] sim ≥ 0.38
        # Diagnostics
        "issues": issues,
    }
