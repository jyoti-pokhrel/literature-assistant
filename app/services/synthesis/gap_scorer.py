from __future__ import annotations

import math
from datetime import datetime, timezone, timedelta

NEPAL_TZ = timezone(timedelta(hours=5, minutes=45))


def _current_year() -> int:
    return datetime.now(NEPAL_TZ).year


# Sub-score functions


def _recurrence_score(cluster_papers: list[dict], all_papers: list[dict]) -> float:

    if not all_papers:
        return 0.0
    raw = len(cluster_papers) / len(all_papers)

    return min(1.0, raw * 1.5)


def _evidence_strength_score(cluster_papers: list[dict]) -> float:

    token_set: set[str] = set()
    for paper in cluster_papers:
        for lim in paper.get("normalized_limitations") or []:
            if lim:
                token_set.add(lim.strip().lower())
        for fw in paper.get("normalized_future_work") or []:
            if fw:
                token_set.add(fw.strip().lower())
    n_distinct = len(token_set)

    return min(1.0, math.log1p(n_distinct) / math.log1p(10))


def _recency_score(cluster_papers: list[dict]) -> float:

    cy = _current_year()
    if not cluster_papers:
        return 0.5

    weights = []
    for paper in cluster_papers:
        year = paper.get("year")
        if not year:
            weights.append(0.5)
            continue
        age = max(cy - int(year), 0)
        if age <= 2:
            weights.append(1.0)
        elif age <= 4:
            weights.append(0.8)
        elif age <= 6:
            weights.append(0.6)
        else:
            weights.append(0.4)
    return sum(weights) / len(weights) if weights else 0.5


def _coverage_impact_score(cluster_papers: list[dict], all_papers: list[dict]) -> float:

    cluster_fw: set[str] = set()
    for paper in cluster_papers:
        cluster_fw.update(paper.get("normalized_future_work") or [])

    global_fw: set[str] = set()
    for paper in all_papers:
        global_fw.update(paper.get("normalized_future_work") or [])

    if not global_fw:
        return 0.5
    if not cluster_fw:
        return 0.0

    intersection = len(cluster_fw & global_fw)
    union = len(cluster_fw | global_fw)
    return intersection / union if union > 0 else 0.0


def _novelty_score(cluster_papers: list[dict]) -> float:

    if not cluster_papers:
        return 0.5

    cy = _current_year()
    novelty_values = []
    for paper in cluster_papers:
        cites = max(paper.get("citation_count") or 0, 0)
        year = paper.get("year")
        age = max((cy - int(year)), 1) if year else 5
        # Citations per year, capped
        rate = min(cites / age, 100)
        # Invert: high citation rate = low novelty
        novelty_values.append(1.0 - (rate / 100))
    return sum(novelty_values) / len(novelty_values)


# Main scoring function
def compute_gap_score(
    cluster_papers: list[dict],
    all_papers: list[dict],
) -> float:

    if not cluster_papers:
        return 0.05

    recurrence = _recurrence_score(cluster_papers, all_papers)
    evidence_strength = _evidence_strength_score(cluster_papers)
    recency = _recency_score(cluster_papers)
    coverage_impact = _coverage_impact_score(cluster_papers, all_papers)
    novelty = _novelty_score(cluster_papers)

    raw = (
        0.35 * recurrence
        + 0.25 * evidence_strength
        + 0.15 * recency
        + 0.15 * coverage_impact
        + 0.10 * novelty
    )

    return round(min(0.99, max(0.05, raw)), 3)
