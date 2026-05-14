"""Rank candidate papers against a user's profile vector.

Pipeline:
  1. $vectorSearch over `papers.embedding` against the profile.
  2. Filter out previously-seen paper ids in Python.
  3. Composite score = 0.65·vector + 0.15·recency + 0.10·log10(citations) + 0.10·affinity.
  4. MMR (λ=0.7) over the top scored to diversify.
  5. Attach a `reason` string built from the nearest profile component.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import logging
import math

from app.db.session import papers_collection
from app.services.recommendations.scoring import (
    citation_score,
    composite_score,
    cosine,
    interleave_by_weight,
    recency_score,
)

logger = logging.getLogger(__name__)

VECTOR_INDEX_NAME = "papers_vector_index"
NUM_CANDIDATES = 200
VECTOR_LIMIT = 120
MMR_LAMBDA = 0.7
TOP_COMPONENTS_FOR_RETRIEVAL = 5


def _format_search_date(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        dt = _dt.datetime.fromisoformat(iso)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return ""


def build_reason(paper_vec: list[float], profile_components: list[dict]) -> str:
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
        sim = cosine(paper_vec, component["_vector"])
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


def hydrate_components(profile_components: list[dict], embed_lookup) -> list[dict]:
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
                cosine(candidate.get("embedding") or [], s.get("embedding") or [])
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
    affinity_profile=None,
) -> list[dict]:
    """Return up to `page_size` ranked candidate papers.

    Issues one `$vectorSearch` per top profile component (plus the centroid
    as a fallback), interleaves the per-component lists by weight, then
    composite-scores the union and applies MMR for diversity.
    """
    seen = set(seen_paper_ids or [])

    hydrated = hydrate_components(profile_components, embed_lookup)
    positives = [c for c in hydrated if c.get("weight", 0) > 0]
    positives.sort(key=lambda c: c["weight"], reverse=True)

    queries: list[tuple[list[float], float, dict | None]] = []
    if positives:
        for component in positives[:TOP_COMPONENTS_FOR_RETRIEVAL]:
            queries.append((component["_vector"], float(component["weight"]), component))
    if profile_vector:
        queries.append((profile_vector, max(0.5, sum(c["weight"] for c in positives) * 0.3), None))

    if not queries:
        return []

    per_query_raw = await asyncio.gather(
        *(_vector_search(vector) for vector, _w, _comp in queries)
    )

    per_query_filtered: list[list[dict]] = []
    for results in per_query_raw:
        kept = []
        for doc in results:
            external_id = doc.get("external_id")
            if external_id and external_id in seen:
                continue
            kept.append(doc)
        per_query_filtered.append(kept)

    interleaved = interleave_by_weight(
        lists=per_query_filtered,
        weights=[w for _v, w, _c in queries],
        limit=max(page_size * 4, page_size),
        key=lambda d: d.get("external_id") or id(d),
    )

    if not interleaved:
        return []

    for doc in interleaved:
        vector_score = float(doc.get("vector_score") or 0.0)
        recency = recency_score(doc.get("year"))
        citations = citation_score(doc.get("citation_count"))
        if affinity_profile is not None:
            from app.services.recommendations.affinity import affinity_score_for_paper
            affinity = affinity_score_for_paper(doc, affinity_profile)
        else:
            affinity = 0.0
        doc["_final_score"] = composite_score(vector_score, recency, citations, affinity)

    interleaved.sort(key=lambda d: d["_final_score"], reverse=True)
    selected = _mmr_select(interleaved, page_size)

    for item in selected:
        item["reason"] = build_reason(item.get("embedding") or [], hydrated)
        item["score"] = round(float(item.get("_final_score", 0.0)), 4)

    return selected


async def rank_in_memory(
    query_vectors: list[list[float]],
    weights: list[float],
    candidates: list[dict],
    seen_ids: set[str],
    page_size: int,
    affinity_profile=None,
) -> list[dict]:
    """Cosine-rank candidates that already have an `embedding` in memory.

    Used when Atlas Vector Search has not yet indexed freshly-fetched papers,
    or when we want to score a small pool without an extra Atlas round-trip.
    `query_vectors` are typically the per-component profile vectors; weights
    line up positionally. The best similarity across queries is used as the
    `vector_score` to keep behavior consistent with multi-query retrieval.
    """
    if not query_vectors or not candidates or page_size <= 0:
        return []

    scored: list[dict] = []
    for paper in candidates:
        external_id = paper.get("external_id")
        if not external_id or external_id in seen_ids:
            continue
        embedding = paper.get("embedding")
        if not isinstance(embedding, list) or not embedding:
            continue
        best_sim = 0.0
        for q, w in zip(query_vectors, weights):
            if w <= 0:
                continue
            sim = cosine(embedding, q)
            if sim > best_sim:
                best_sim = sim
        recency = recency_score(paper.get("year"))
        citations = citation_score(paper.get("citation_count"))
        if affinity_profile is not None:
            from app.services.recommendations.affinity import affinity_score_for_paper
            affinity = affinity_score_for_paper(paper, affinity_profile)
        else:
            affinity = 0.0
        final = composite_score(best_sim, recency, citations, affinity=affinity)
        out = dict(paper)
        out["vector_score"] = best_sim
        out["_final_score"] = final
        scored.append(out)

    scored.sort(key=lambda d: d["_final_score"], reverse=True)
    return scored[:page_size]
