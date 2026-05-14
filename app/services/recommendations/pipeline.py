"""Top-level orchestrator for the personalized explore feed.

Public entry point: `get_feed_page(username, cursor, page_size)`.
Flow:
  1. Load (or rebuild) the user's profile. Raises ColdStartRequired if empty.
  2. Run `ranker.rank_for_profile` against the persisted paper embeddings.
  3. If the candidate pool is thin, block once on `candidate_fetcher.fetch_for_topics`,
     then re-run the rank.
  4. Always kick off an async fetcher.replenish for the next call.
  5. Record the chosen paper ids in the user's seen-impression ring buffer.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from app.services.recommendations.candidate_fetcher import (
    fetch_for_topics,
    replenish,
)
from app.services.recommendations.embedder import embed_texts
from app.services.recommendations.profile_builder import (
    load_profile,
    record_impressions,
)
from app.services.recommendations.ranker import (
    _build_reason,
    _hydrate_components,
    rank_for_profile,
    rank_in_memory,
)

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 20
MIN_POOL_FOR_PAGE = 0.5  # if fewer than 50% of page_size returned, do an inline fetch


class ColdStartRequired(Exception):
    """Raised when the user has no usable signal yet — UI should run onboarding."""


@dataclass
class FeedPage:
    papers: list[dict]
    next_cursor: int
    has_more: bool
    profile_summary: dict


def _make_embed_lookup(labels: list[str]) -> tuple[Any, Any]:
    """Returns (async_prepare, sync_lookup) used by ranker._hydrate_components.

    Calling `await async_prepare()` populates an internal map; `sync_lookup(label)`
    then returns the vector or None. Separated this way because ranker calls the
    lookup repeatedly during MMR but the embedding work should run once.
    """
    cache: dict[str, list[float]] = {}

    async def prepare() -> None:
        if not labels:
            return
        vectors = await embed_texts(labels)
        for label, vector in zip(labels, vectors):
            cache[label] = vector

    def lookup(label: str):
        return cache.get(label)

    return prepare, lookup


def _profile_summary(profile) -> dict:
    return {
        "top_topics": profile.top_topics,
        "seed_topics": profile.seed_topics,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
        "component_counts": _count_kinds(profile.components),
    }


def _count_kinds(components) -> dict:
    counts: dict[str, int] = {}
    for component in components or []:
        kind = getattr(component, "kind", None) or (
            component.get("kind") if isinstance(component, dict) else None
        )
        if not kind:
            continue
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def _serialize_paper(doc: dict) -> dict:
    return {
        "source": doc.get("source"),
        "external_id": doc.get("external_id"),
        "title": doc.get("title"),
        "abstract": doc.get("abstract"),
        "authors": doc.get("authors") or [],
        "year": doc.get("year"),
        "venue": doc.get("venue"),
        "url": doc.get("url"),
        "pdf_url": doc.get("pdf_url"),
        "citation_count": doc.get("citation_count"),
        "doi": doc.get("doi"),
        "reason": doc.get("reason") or "",
        "score": doc.get("score") or 0.0,
    }


async def get_feed_page(
    username: str,
    cursor: int = 0,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> FeedPage:
    profile = await load_profile(username)
    if profile.is_cold_start or not profile.vector:
        raise ColdStartRequired()

    component_dicts = [
        {"kind": c.kind, "label": c.label, "weight": c.weight, "meta": c.meta}
        for c in profile.components
    ]
    positive_labels = [
        c["label"] for c in component_dicts if c["weight"] > 0 and c.get("label")
    ]
    prepare_lookup, lookup = _make_embed_lookup(positive_labels)
    await prepare_lookup()

    topics = [
        c["label"]
        for c in sorted(
            component_dicts, key=lambda c: abs(c.get("weight", 0)), reverse=True
        )
        if c.get("label")
    ]

    atlas_ranked = await rank_for_profile(
        profile_vector=profile.vector,
        profile_components=component_dicts,
        seen_paper_ids=profile.seen_paper_ids,
        page_size=page_size * 2,  # over-fetch so we can dedup against fresh
        embed_lookup=lookup,
    )

    fresh_candidates: list[dict] = []
    seen_set = set(profile.seen_paper_ids or [])

    if len(atlas_ranked) < max(1, int(page_size * MIN_POOL_FOR_PAGE)):
        fresh_candidates = await fetch_for_topics(topics)

        query_vectors: list[list[float]] = []
        query_weights: list[float] = []
        for component in component_dicts:
            if component["weight"] <= 0:
                continue
            vector = lookup(component["label"])
            if not vector:
                continue
            query_vectors.append(vector)
            query_weights.append(float(component["weight"]))
        if not query_vectors and profile.vector:
            query_vectors = [profile.vector]
            query_weights = [1.0]

        atlas_ids = {p.get("external_id") for p in atlas_ranked if p.get("external_id")}
        seen_for_inmem = seen_set | atlas_ids
        in_mem_ranked = await rank_in_memory(
            query_vectors=query_vectors,
            weights=query_weights,
            candidates=fresh_candidates,
            seen_ids=seen_for_inmem,
            page_size=page_size * 2,
        )
        hydrated = _hydrate_components(component_dicts, lookup)
        for item in in_mem_ranked:
            item["reason"] = _build_reason(item.get("embedding") or [], hydrated)
            item["score"] = round(float(item.get("_final_score", 0.0)), 4)

        merged = atlas_ranked + in_mem_ranked
        merged.sort(key=lambda d: d.get("_final_score") or d.get("score") or 0.0, reverse=True)
        ranked = merged[: page_size * 2]
    else:
        ranked = atlas_ranked

    if ranked and topics:
        asyncio.create_task(replenish(topics))

    if cursor > 0:
        ranked = ranked[cursor : cursor + page_size] if cursor < len(ranked) else []
    else:
        ranked = ranked[:page_size]

    chosen_ids = [doc.get("external_id") for doc in ranked if doc.get("external_id")]
    if chosen_ids:
        await record_impressions(username, chosen_ids)

    serialized = [_serialize_paper(doc) for doc in ranked]
    has_more = len(ranked) >= page_size
    next_cursor = cursor + len(ranked)

    return FeedPage(
        papers=serialized,
        next_cursor=next_cursor,
        has_more=has_more,
        profile_summary=_profile_summary(profile),
    )
