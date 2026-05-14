"""Popular-page ranker for users with no (or weak) profile vector.

Powers the first-visit explore feed. The score is a simple blend of
recency and citation popularity — fast, deterministic, and explainable.
Diversity is enforced by capping the number of papers per venue per page;
once any venue saturates the cap, we relax it to keep the page filled.
"""
from __future__ import annotations

import logging

from app.db.session import papers_collection
from app.services.recommendations.scoring import citation_score, recency_score

logger = logging.getLogger(__name__)

POOL_LIMIT = 500
PER_VENUE_CAP = 3
RECENCY_BLEND = 0.55
CITATION_BLEND = 0.45


def _popular_score(paper: dict) -> float:
    recency = recency_score(paper.get("year"))
    citations = citation_score(paper.get("citation_count"))
    return RECENCY_BLEND * recency + CITATION_BLEND * citations


def _diversify_by_venue(
    items: list[dict],
    page_size: int,
    per_venue_cap: int = PER_VENUE_CAP,
) -> list[dict]:
    """Cap items per venue while preserving rank order. Relaxes the cap if
    the page would otherwise be short — better one venue twice than a half page."""
    if not items or page_size <= 0:
        return []
    out: list[dict] = []
    venue_counts: dict[str, int] = {}
    overflow: list[dict] = []
    for item in items:
        venue = (item.get("venue") or "").strip().lower() or "_unknown"
        if venue_counts.get(venue, 0) < per_venue_cap:
            out.append(item)
            venue_counts[venue] = venue_counts.get(venue, 0) + 1
            if len(out) >= page_size:
                return out
        else:
            overflow.append(item)
    # Cap relaxed: pull from overflow until the page is full.
    for item in overflow:
        if len(out) >= page_size:
            break
        out.append(item)
    return out


async def rank_popular(
    seen_paper_ids: set[str],
    page_size: int,
) -> list[dict]:
    """Return up to `page_size` recency + citations ranked papers from the DB.

    Filters out previously-seen ids and applies a per-venue diversity cap.
    Returns `[]` if the embedded paper pool is empty — the caller is
    responsible for the next-level fallback (direct topic fetch).
    """
    if papers_collection is None or page_size <= 0:
        return []
    try:
        cursor = papers_collection.find(
            {"embedding": {"$exists": True}},
            projection={
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
                "embedding": 1,
            },
        ).limit(POOL_LIMIT)
        pool = [doc async for doc in cursor]
    except Exception:
        logger.exception("rank_popular: pool fetch failed")
        return []

    filtered = []
    for paper in pool:
        eid = paper.get("external_id")
        if eid and eid in seen_paper_ids:
            continue
        paper["_pop_score"] = _popular_score(paper)
        paper["_final_score"] = paper["_pop_score"]
        filtered.append(paper)

    filtered.sort(key=lambda d: d["_pop_score"], reverse=True)
    selected = _diversify_by_venue(filtered, page_size=page_size)

    for item in selected:
        item["reason"] = "Trending recently"
        item["score"] = round(float(item.get("_pop_score", 0.0)), 4)
    return selected
