"""Fetch fresh paper candidates from arXiv + Semantic Scholar.

Driven by the top topics in a user's profile. Results are deduplicated
against existing `papers` entries (by source+external_id) and the surviving
new candidates are embedded via `embedder.ensure_paper_embeddings`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Iterable

from app.db.session import papers_collection
from app.schemas.paper import RetrievedPaper
from app.services.extraction.normalizer import deduplicate_papers
from app.services.recommendations.embedder import ensure_paper_embeddings
from app.services.retrieval.arxiv_client import search_arxiv
from app.services.retrieval.semantic_scholar_client import search_semantic_scholar

logger = logging.getLogger(__name__)

PER_TOPIC_LIMIT = 20
TOP_TOPICS_TO_FETCH = 3


def _paper_to_dict(paper: RetrievedPaper) -> dict:
    if hasattr(paper, "model_dump"):
        return paper.model_dump()
    if hasattr(paper, "dict"):
        return paper.dict()
    return dict(paper)


async def _existing_keys(papers: Iterable[dict]) -> set[tuple[str, str]]:
    if papers_collection is None:
        return set()
    keys = [
        (p.get("source"), p.get("external_id"))
        for p in papers
        if p.get("source") and p.get("external_id")
    ]
    if not keys:
        return set()
    or_clauses = [{"source": s, "external_id": eid} for s, eid in keys]
    found: set[tuple[str, str]] = set()
    try:
        cursor = papers_collection.find(
            {"$or": or_clauses, "embedding": {"$exists": True}},
            projection={"source": 1, "external_id": 1},
        )
        async for doc in cursor:
            found.add((doc.get("source"), doc.get("external_id")))
    except Exception:
        logger.exception("existing_keys lookup failed")
    return found


async def fetch_for_topics(topics: list[str]) -> list[dict]:
    """Pull candidates from arXiv + S2 across the given topics and embed-new ones."""
    if not topics:
        return []
    selected = topics[:TOP_TOPICS_TO_FETCH]

    tasks = []
    for topic in selected:
        tasks.append(search_arxiv(topic, limit=PER_TOPIC_LIMIT))
        tasks.append(search_semantic_scholar(topic, limit=PER_TOPIC_LIMIT))

    raw_results = await asyncio.gather(*tasks, return_exceptions=True)
    merged_papers: list[RetrievedPaper] = []
    for result in raw_results:
        if isinstance(result, Exception):
            logger.warning("Candidate fetch failed: %s", result)
            continue
        merged_papers.extend(result or [])

    deduped = deduplicate_papers(merged_papers)
    candidate_dicts = [_paper_to_dict(p) for p in deduped]

    existing = await _existing_keys(candidate_dicts)
    fresh = [
        c
        for c in candidate_dicts
        if (c.get("source"), c.get("external_id")) not in existing
    ]

    if not fresh:
        return candidate_dicts

    await ensure_paper_embeddings(fresh)
    return candidate_dicts


async def replenish(topics: list[str]) -> None:
    """Fire-and-forget pool warmer used by pipeline.get_feed_page."""
    try:
        await fetch_for_topics(topics)
    except Exception:
        logger.exception("Candidate replenish failed")
