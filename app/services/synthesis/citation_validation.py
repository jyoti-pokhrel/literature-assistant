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

    return {
        # Core flags
        "is_grounded":   status in ("grounded", "weakly_supported"),
        "status":        status,
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
