from __future__ import annotations

import re
from typing import Any


def validate_gap_citations(gap_fields: dict[str, Any], citations: list[Any]) -> dict[str, Any]:
    """Validate whether a gap is grounded in numbered paper references."""
    citation_count = len(citations)
    text = " ".join(str(gap_fields.get(field, "") or "") for field in (
        "description",
        "what_fails",
        "missing_piece",
        "why_it_exists",
        "proposed_direction",
    ))
    cited_numbers = sorted({int(match.group(1)) for match in re.finditer(r"\[(\d+)\]", text)})
    invalid_refs = [number for number in cited_numbers if number < 1 or number > citation_count]
    evidence_count = 0
    for citation in citations:
        evidence = getattr(citation, "extracted_evidence", None)
        if evidence is None and isinstance(citation, dict):
            evidence = citation.get("extracted_evidence")
        evidence_count += len(evidence or [])

    issues: list[str] = []
    if not cited_numbers:
        issues.append("No numeric citation markers found in core gap fields.")
    if invalid_refs:
        issues.append(f"Invalid citation markers: {', '.join(f'[{n}]' for n in invalid_refs)}.")
    if citation_count == 0:
        issues.append("No supporting citation objects attached.")
    if evidence_count == 0:
        issues.append("No extracted limitation or future-work evidence attached.")

    return {
        "is_grounded": not issues,
        "status": "grounded" if not issues else "needs_review",
        "cited_marker_count": len(cited_numbers),
        "supporting_paper_count": citation_count,
        "evidence_snippet_count": evidence_count,
        "invalid_references": invalid_refs,
        "issues": issues,
    }
