"""Pure scoring helpers for the recommendation ranker.

Lives outside `ranker.py` so the functions can be unit-tested without
touching Mongo. All inputs are plain numbers/vectors; no I/O.
"""
from __future__ import annotations

import datetime as _dt
import math
from typing import Any, Sequence

import numpy as np

RECENCY_FLOOR_YEAR = 2020
VECTOR_WEIGHT = 0.65
RECENCY_WEIGHT = 0.15
CITATION_WEIGHT = 0.10
AFFINITY_WEIGHT = 0.10


def recency_score(year: Any) -> float:
    try:
        year_int = int(year)
    except (TypeError, ValueError):
        return 0.0
    current_year = _dt.datetime.now(_dt.timezone.utc).year
    denom = max(1, current_year - RECENCY_FLOOR_YEAR)
    return max(0.0, min(1.0, (year_int - RECENCY_FLOOR_YEAR) / denom))


def citation_score(citation_count: Any) -> float:
    try:
        count = max(0, int(citation_count or 0))
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, math.log10(1 + count) / 4.0)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    av = np.asarray(a, dtype=np.float32)
    bv = np.asarray(b, dtype=np.float32)
    denom = float(np.linalg.norm(av) * np.linalg.norm(bv))
    if denom < 1e-9:
        return 0.0
    return float(np.dot(av, bv) / denom)


def composite_score(
    vector_score: float,
    recency: float,
    citations: float,
    affinity: float,
) -> float:
    return (
        VECTOR_WEIGHT * vector_score
        + RECENCY_WEIGHT * recency
        + CITATION_WEIGHT * citations
        + AFFINITY_WEIGHT * affinity
    )


def interleave_by_weight(
    lists: list[list[dict]],
    weights: list[float],
    limit: int,
    key,
) -> list[dict]:
    """Round-robin pick items from ranked lists in proportion to weights.

    Each list is consumed front-to-back. The next list picked is the one with
    the highest `weight / (1 + picks_so_far)` value (deficit round-robin).
    `key` is a callable returning a hashable id for dedup across lists.
    """
    if not lists or limit <= 0:
        return []
    cursors = [0] * len(lists)
    picks = [0] * len(lists)
    seen: set = set()
    out: list[dict] = []

    while len(out) < limit:
        # pick the list with highest weight/(1+picks) that still has items
        best_idx = -1
        best_priority = -math.inf
        for i, lst in enumerate(lists):
            if cursors[i] >= len(lst):
                continue
            priority = weights[i] / (1.0 + picks[i])
            if priority > best_priority:
                best_priority = priority
                best_idx = i
        if best_idx == -1:
            break  # all lists exhausted
        # advance cursor on the chosen list until we find a fresh item
        while cursors[best_idx] < len(lists[best_idx]):
            candidate = lists[best_idx][cursors[best_idx]]
            cursors[best_idx] += 1
            cid = key(candidate)
            if cid in seen:
                continue
            seen.add(cid)
            out.append(candidate)
            picks[best_idx] += 1
            break
    return out
