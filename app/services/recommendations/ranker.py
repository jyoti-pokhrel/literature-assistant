"""Rank candidate papers against a user's profile vector.

Pipeline:
  1. $vectorSearch over `papers.embedding` against the profile.
  2. Filter out previously-seen paper ids in Python.
  3. Composite score = 0.70·vector + 0.20·recency + 0.10·log10(citations).
  4. MMR (λ=0.7) over the top scored to diversify.
  5. Attach a `reason` string built from the nearest profile component.
"""

from __future__ import annotations

import datetime as _dt
import logging
import math
from typing import Any

import numpy as np

from app.db.session import papers_collection

logger = logging.getLogger(__name__)

VECTOR_INDEX_NAME = "papers_vector_index"
NUM_CANDIDATES = 200
VECTOR_LIMIT = 120
MMR_LAMBDA = 0.7
RECENCY_FLOOR_YEAR = 2020
VECTOR_WEIGHT = 0.70
RECENCY_WEIGHT = 0.20
CITATION_WEIGHT = 0.10


def _recency_score(year: Any) -> float:
    try:
        year_int = int(year)
    except (TypeError, ValueError):
        return 0.0
    current_year = _dt.datetime.now(_dt.timezone.utc).year
    denom = max(1, current_year - RECENCY_FLOOR_YEAR)
    return max(0.0, min(1.0, (year_int - RECENCY_FLOOR_YEAR) / denom))


def _citation_score(citation_count: Any) -> float:
    try:
        count = max(0, int(citation_count or 0))
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, math.log10(1 + count) / 4.0)


def _cosine(a: list[float] | np.ndarray, b: list[float] | np.ndarray) -> float:
    av = np.asarray(a, dtype=np.float32)
    bv = np.asarray(b, dtype=np.float32)
    denom = float(np.linalg.norm(av) * np.linalg.norm(bv))
    if denom < 1e-9:
        return 0.0
    return float(np.dot(av, bv) / denom)


def _format_search_date(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        dt = _dt.datetime.fromisoformat(iso)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return ""


def _build_reason(paper_vec: list[float], profile_components: list[dict]) -> str:
    if not profile_components:
        return "Matches your interests"
    positives = [
        c for c in profile_components if c.get("weight", 0) > 0 and c.get("_vector")
    ]
    if not positives:
        return "Newly indexed in your area"

    best_sim = -1.0
    best = positives[0]
    for component in positives:
        sim = _cosine(paper_vec, component["_vector"])
        if sim > best_sim:
            best_sim = sim
            best = component

    kind = best.get("kind", "")
    label = best.get("label", "your interests")
    if kind == "seed":
        return f"Matches your interest in '{label}'"
    if kind == "search":
        ts = _format_search_date(best.get("meta", {}).get("ts"))
        if ts:
            return f"Similar to your search on '{label}' on {ts}"
        return f"Similar to your search on '{label}'"
    if kind == "gap_positive":
        return f"Related to a gap you upvoted: '{label}'"
    return f"Matches your interest in '{label}'"


async def _vector_search(query: list[float]) -> list[dict]:
    if papers_collection is None:
        return []
    pipeline = [
        {
            "$vectorSearch": {
                "index": VECTOR_INDEX_NAME,
                "path": "embedding",
                "queryVector": query,
                "numCandidates": NUM_CANDIDATES,
                "limit": VECTOR_LIMIT,
            }
        },
        {"$addFields": {"vector_score": {"$meta": "vectorSearchScore"}}},
    ]
    try:
        cursor = papers_collection.aggregate(pipeline)
        return [doc async for doc in cursor]
    except Exception:
        logger.exception("$vectorSearch failed; returning empty rank")
        return []


def _hydrate_components(profile_components: list[dict], embed_lookup) -> list[dict]:
    """Attach the per-component vector by re-embedding labels.

    Profile components are persisted without their vectors (vectors are heavy
    and ephemeral). For reason-attribution we need them at rank time. The
    caller passes `embed_lookup` — a sync callable label->vector — which is
    built once per ranking call by embedding all positive-component labels.
    """
    hydrated = []
    for component in profile_components:
        vector = embed_lookup(component.get("label", ""))
        if vector is None:
            continue
        copy = dict(component)
        copy["_vector"] = vector
        hydrated.append(copy)
    return hydrated


def _mmr_select(
    items: list[dict],
    page_size: int,
    lambda_: float = MMR_LAMBDA,
) -> list[dict]:
    if not items:
        return []
    if len(items) <= page_size:
        return items

    selected: list[dict] = []
    remaining = list(items)
    while remaining and len(selected) < page_size:
        if not selected:
            best = max(remaining, key=lambda x: x["_final_score"])
            selected.append(best)
            remaining.remove(best)
            continue

        best_score = -math.inf
        best_item = None
        for candidate in remaining:
            relevance = candidate["_final_score"]
            redundancy = max(
                _cosine(candidate.get("embedding") or [], s.get("embedding") or [])
                for s in selected
            )
            mmr_score = lambda_ * relevance - (1 - lambda_) * redundancy
            if mmr_score > best_score:
                best_score = mmr_score
                best_item = candidate
        if best_item is None:
            break
        selected.append(best_item)
        remaining.remove(best_item)
    return selected


async def rank_for_profile(
    profile_vector: list[float],
    profile_components: list[dict],
    seen_paper_ids: list[str],
    page_size: int,
    embed_lookup,
) -> list[dict]:
    """Return up to `page_size` ranked candidate papers."""
    raw = await _vector_search(profile_vector)
    if not raw:
        return []

    seen = set(seen_paper_ids or [])
    filtered = []
    for doc in raw:
        external_id = doc.get("external_id")
        if external_id and external_id in seen:
            continue
        vector_score = float(doc.get("vector_score") or 0.0)
        recency = _recency_score(doc.get("year"))
        citations = _citation_score(doc.get("citation_count"))
        final = (
            VECTOR_WEIGHT * vector_score
            + RECENCY_WEIGHT * recency
            + CITATION_WEIGHT * citations
        )
        doc["_final_score"] = final
        filtered.append(doc)

    filtered.sort(key=lambda d: d["_final_score"], reverse=True)
    top = filtered[: max(page_size * 4, page_size)]

    selected = _mmr_select(top, page_size)

    hydrated_components = _hydrate_components(profile_components, embed_lookup)

    for item in selected:
        item["reason"] = _build_reason(item.get("embedding") or [], hydrated_components)
        item["score"] = round(float(item.get("_final_score", 0.0)), 4)

    return selected
