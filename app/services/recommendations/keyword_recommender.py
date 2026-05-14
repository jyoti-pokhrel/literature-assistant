"""Keyword-driven Explore recommender.

Replaces the vector-search pipeline with a deterministic, no-Atlas-index path:

  * Users with search history → TF-IDF cosine match between their recent
    topics and the candidate pool's title + abstract.
  * Users with no search history → highly cited papers, pulled from the
    local corpus first and topped up from Semantic Scholar if thin.

The caller (`app.api.routes.explore`) receives a 4-tuple matching the
existing ExploreFeedResponse shape, so the API contract is unchanged.
"""

from __future__ import annotations

import logging
from typing import Iterable

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.db.session import papers_collection, user_profiles_collection
from app.services.recommendations.candidate_fetcher import fetch_for_topics
from app.services.recommendations.profile_builder import (
    SEEN_EXPIRY_DAYS,
    record_impressions,
)
from app.services.recommendations.signals import fetch_search_signals

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 20
LOCAL_POOL_LIMIT = 500
RECENT_TOPICS_TO_USE = 5
TOPICS_TO_FETCH = 3
OVERFETCH_MULTIPLIER = 5
# Cap so impressions don't exhaust a small corpus. With ~150 papers, allowing
# the full ring buffer (up to 1000 ids) means a returning user matches every
# paper as "seen" and the feed empties. Filter against the most recent N only.
SEEN_FILTER_LIMIT = 30

DEFAULT_COLD_TOPICS = [
    "machine learning",
    "deep learning",
    "neural networks",
    "language models",
    "computer vision",
]


def _doc_text(doc: dict) -> str:
    title = doc.get("title") or ""
    abstract = doc.get("abstract") or ""
    return f"{title}. {abstract}".strip()


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


async def _load_seen_ids(username: str) -> set[str]:
    """Last ~SEEN_FILTER_LIMIT impression ids for the user.

    Returning the full history would dwarf the local paper corpus and
    filter every result out. We only deduplicate against the most-recent
    impressions and accept that older ones may resurface.
    """
    if user_profiles_collection is None or not username:
        return set()
    doc = await user_profiles_collection.find_one({"username": username})
    if not doc:
        return set()

    impressions = doc.get("seen_impressions") or []
    timestamped: list[tuple] = []
    untimed: list[str] = []
    for entry in impressions:
        if not isinstance(entry, dict):
            continue
        eid = entry.get("id")
        if not eid:
            continue
        ts = entry.get("ts")
        if ts is None:
            untimed.append(eid)
        else:
            timestamped.append((ts, eid))
    timestamped.sort(reverse=True)

    seen: list[str] = []
    for _, eid in timestamped:
        seen.append(eid)
        if len(seen) >= SEEN_FILTER_LIMIT:
            break
    if len(seen) < SEEN_FILTER_LIMIT:
        for eid in untimed:
            seen.append(eid)
            if len(seen) >= SEEN_FILTER_LIMIT:
                break
    if len(seen) < SEEN_FILTER_LIMIT:
        for eid in doc.get("seen_paper_ids") or []:
            if eid:
                seen.append(eid)
                if len(seen) >= SEEN_FILTER_LIMIT:
                    break
    return set(seen)


_LOCAL_PROJECTION = {
    "source": 1,
    "external_id": 1,
    "title": 1,
    "abstract": 1,
    "authors": 1,
    "year": 1,
    "venue": 1,
    "url": 1,
    "pdf_url": 1,
    "citation_count": 1,
    "doi": 1,
}


async def _load_local_pool(seen_ids: set[str], limit: int) -> list[dict]:
    """Fetch local candidates. Drops the seen filter if the result is thin
    so a user with a saturated impression history still gets papers."""
    if papers_collection is None:
        return []

    async def _fetch(query: dict) -> list[dict]:
        cursor = papers_collection.find(query, projection=_LOCAL_PROJECTION).limit(limit)
        return [doc async for doc in cursor]

    if seen_ids:
        filtered = await _fetch({"external_id": {"$nin": list(seen_ids)}})
        if filtered:
            return filtered
    return await _fetch({})


def _merge_unique(*pools: Iterable[dict]) -> list[dict]:
    seen_keys: set[tuple] = set()
    merged: list[dict] = []
    for pool in pools:
        for paper in pool:
            key = (paper.get("source"), paper.get("external_id"))
            if key == (None, None):
                key = (None, paper.get("url") or paper.get("title"))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            merged.append(paper)
    return merged


async def _highly_cited_papers(seen_ids: set[str], page_size: int) -> list[dict]:
    """Cold-start path: highly cited papers, preferring arXiv-sourced.

    Tries three sources in order so the page is never empty when local data
    exists:
      1. Local corpus with `citation_count > 0`, ranked by citations desc.
      2. Live fetch (S2 + arXiv) for the default topics, kept if cited.
      3. Local corpus regardless of citation count, ranked by year desc.
    """
    cited_pool: list[dict] = []
    if papers_collection is not None:
        query: dict = {"citation_count": {"$gt": 0}}
        if seen_ids:
            query["external_id"] = {"$nin": list(seen_ids)}
        cursor = (
            papers_collection.find(query)
            .sort("citation_count", -1)
            .limit(page_size * 3)
        )
        cited_pool.extend([doc async for doc in cursor])

    if len(cited_pool) < page_size:
        try:
            fresh = await fetch_for_topics(DEFAULT_COLD_TOPICS)
        except Exception:
            logger.exception("cold-start fresh fetch failed")
            fresh = []
        fresh_with_cites = [
            p
            for p in fresh
            if p.get("external_id") not in seen_ids
            and (p.get("citation_count") or 0) > 0
        ]
        cited_pool = _merge_unique(cited_pool, fresh_with_cites)

    cited_pool.sort(key=lambda p: p.get("citation_count") or 0, reverse=True)
    for paper in cited_pool:
        cites = paper.get("citation_count") or 0
        paper["reason"] = f"Highly cited ({cites} citations)"
        paper["score"] = float(cites)

    if len(cited_pool) >= page_size or papers_collection is None:
        return cited_pool

    async def _fetch_recent(query: dict) -> list[dict]:
        cursor = (
            papers_collection.find(query)
            .sort("year", -1)
            .limit(page_size * 3)
        )
        return [doc async for doc in cursor]

    recent: list[dict] = []
    if seen_ids:
        recent = await _fetch_recent({"external_id": {"$nin": list(seen_ids)}})
    if not recent:
        recent = await _fetch_recent({})

    existing_ids = {p.get("external_id") for p in cited_pool if p.get("external_id")}
    for paper in recent:
        if paper.get("external_id") in existing_ids:
            continue
        paper["reason"] = "Recent on arXiv"
        paper["score"] = 0.0
        cited_pool.append(paper)
    return cited_pool


def _tfidf_rank(topics: list[str], candidates: list[dict]) -> list[dict]:
    if not candidates or not topics:
        return []
    doc_texts = [_doc_text(d) for d in candidates]
    if not any(doc_texts):
        return []

    vectorizer = TfidfVectorizer(
        stop_words="english",
        ngram_range=(1, 2),
        max_features=20000,
        lowercase=True,
    )
    try:
        matrix = vectorizer.fit_transform(doc_texts + topics)
    except ValueError:
        return []
    doc_matrix = matrix[: len(candidates)]
    topic_matrix = matrix[len(candidates):]

    sims = cosine_similarity(doc_matrix, topic_matrix)
    if sims.size == 0:
        return []
    summed = sims.sum(axis=1)
    best_topic_idx = sims.argmax(axis=1)

    ranked: list[dict] = []
    for i, paper in enumerate(candidates):
        score = float(summed[i])
        if score <= 0.0:
            continue
        item = dict(paper)
        item["score"] = round(score, 4)
        topic_label = topics[int(best_topic_idx[i])] if topics else ""
        item["reason"] = (
            f"Matches your search '{topic_label}'" if topic_label else "Keyword match"
        )
        ranked.append(item)
    ranked.sort(key=lambda d: d["score"], reverse=True)
    return ranked


async def _recent_topics(username: str, client_topics: list[str] | None = None) -> list[str]:
    """Merge server-side `search_history` topics with client-supplied topics.

    Client-supplied topics come from the frontend's localStorage sidebar
    history. They cover gap analyses that don't yet have owner attribution
    in the DB. Server topics take priority (most authoritative) but if
    they're empty, the client list keeps the recommender adapting.
    """
    seen: set[str] = set()
    topics: list[str] = []

    signals = await fetch_search_signals(username)
    for signal in signals:
        topic = (signal.topic or "").strip()
        if not topic or topic.lower() in seen:
            continue
        seen.add(topic.lower())
        topics.append(topic)
        if len(topics) >= RECENT_TOPICS_TO_USE:
            return topics

    for raw in client_topics or []:
        if not isinstance(raw, str):
            continue
        topic = raw.strip()
        if not topic or topic.lower() in seen:
            continue
        seen.add(topic.lower())
        topics.append(topic)
        if len(topics) >= RECENT_TOPICS_TO_USE:
            break
    return topics


async def recommend_for_user(
    username: str,
    cursor: int = 0,
    page_size: int = DEFAULT_PAGE_SIZE,
    client_topics: list[str] | None = None,
) -> tuple[list[dict], int, bool, dict]:
    seen_ids = await _load_seen_ids(username)
    topics = await _recent_topics(username, client_topics=client_topics)

    if not topics:
        ranked = await _highly_cited_papers(seen_ids, page_size * OVERFETCH_MULTIPLIER)
        approach = "highly_cited"
    else:
        local_pool = await _load_local_pool(seen_ids, LOCAL_POOL_LIMIT)
        try:
            fresh = await fetch_for_topics(topics[:TOPICS_TO_FETCH])
        except Exception:
            logger.exception("fetch_for_topics failed; ranking local pool only")
            fresh = []
        fresh = [p for p in fresh if p.get("external_id") not in seen_ids]
        candidates = _merge_unique(local_pool, fresh)
        ranked = _tfidf_rank(topics, candidates)
        approach = "tfidf"
        if not ranked:
            ranked = await _highly_cited_papers(seen_ids, page_size * OVERFETCH_MULTIPLIER)
            approach = "highly_cited_fallback"

    start = max(0, cursor)
    end = start + page_size
    page = ranked[start:end]
    has_more = len(ranked) > end

    chosen_ids = [doc.get("external_id") for doc in page if doc.get("external_id")]
    if chosen_ids:
        await record_impressions(username, chosen_ids)

    summary = {
        "top_topics": topics,
        "seed_topics": topics,
        "approach": approach,
        "candidate_pool": len(ranked),
        "seen_window_days": SEEN_EXPIRY_DAYS,
    }
    return [_serialize_paper(doc) for doc in page], start + len(page), has_more, summary
