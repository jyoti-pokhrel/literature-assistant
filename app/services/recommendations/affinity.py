"""Author/venue affinity profile derived from search history + library saves.

Counts are frequency-weighted with light recency decay. We deliberately keep
this independent of the embedding-based profile so the signal is interpretable
and easy to inspect via `/explore/diagnostics`.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.db.session import (
    library_items_collection,
    search_history_collection,
)

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 60
MAX_AUTHORS = 25
MAX_VENUES = 25


def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


@dataclass
class AffinityProfile:
    authors: dict[str, float] = field(default_factory=dict)
    venues: dict[str, float] = field(default_factory=dict)


async def build_affinity(username: str, user_id: str | None = None) -> AffinityProfile:
    """Aggregate venue/author counts from library_items + search_history."""
    profile = AffinityProfile()
    if not username and not user_id:
        return profile
 
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
 
    if library_items_collection is not None:
        try:
            # For library_items, we'll try user_id first if it was added there, 
            # but legacy items use 'owner' (username).
            query = {"user_id": user_id} if user_id else {"owner": username}
            cursor = library_items_collection.find(
                query,
                projection={"authors": 1, "venue": 1, "added_at": 1, "updated_at": 1},
            ).limit(500)
            async for item in cursor:
                ts = item.get("added_at") or item.get("updated_at")
                weight = _recency_weight(ts, cutoff)
                for author in (item.get("authors") or [])[:8]:
                    key = _norm(author)
                    if not key:
                        continue
                    profile.authors[key] = profile.authors.get(key, 0.0) + weight
                venue_key = _norm(item.get("venue"))
                if venue_key:
                    profile.venues[venue_key] = profile.venues.get(venue_key, 0.0) + weight
        except Exception:
            logger.exception("affinity: library scan failed for %s", username)

    if search_history_collection is not None:
        try:
            query = {"created_at": {"$gte": cutoff}}
            if user_id:
                query["user_id"] = user_id
            else:
                query["username"] = username

            cursor = (
                search_history_collection.find(
                    query,
                    projection={"venue": 1, "created_at": 1},
                )
                .sort("created_at", -1)
                .limit(100)
            )
            async for entry in cursor:
                venue_key = _norm(entry.get("venue"))
                if venue_key:
                    weight = _recency_weight(entry.get("created_at"), cutoff)
                    profile.venues[venue_key] = profile.venues.get(venue_key, 0.0) + weight * 0.5
        except Exception:
            logger.exception("affinity: search_history scan failed for %s", username)

    profile.authors = _top_n(profile.authors, MAX_AUTHORS)
    profile.venues = _top_n(profile.venues, MAX_VENUES)
    _normalize(profile.authors)
    _normalize(profile.venues)
    return profile


def affinity_score_for_paper(paper: dict, profile: AffinityProfile) -> float:
    """Return an affinity score in [0, 1] for a single candidate paper."""
    if not profile.authors and not profile.venues:
        return 0.0
    author_score = 0.0
    for author in (paper.get("authors") or [])[:5]:
        weight = profile.authors.get(_norm(author))
        if weight:
            author_score += weight
    venue = _norm(paper.get("venue"))
    venue_score = 0.0
    if venue:
        for known, w in profile.venues.items():
            if not known:
                continue
            if known == venue:
                venue_score = max(venue_score, w)
                break
            if len(known) >= 4 and len(venue) >= 4 and (known in venue or venue in known):
                venue_score = max(venue_score, w)
                break
    return min(1.0, author_score * 0.6 + venue_score * 0.4)


def _recency_weight(ts, cutoff: datetime) -> float:
    if not isinstance(ts, datetime):
        return 0.4
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    span = max((datetime.now(timezone.utc) - cutoff).total_seconds(), 1.0)
    age = (datetime.now(timezone.utc) - ts).total_seconds()
    return max(0.2, math.exp(-age / span))


def _top_n(counts: dict[str, float], n: int) -> dict[str, float]:
    if len(counts) <= n:
        return counts
    items = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:n]
    return dict(items)


def _normalize(counts: dict[str, float]) -> None:
    if not counts:
        return
    peak = max(counts.values())
    if peak <= 0:
        return
    for key in list(counts.keys()):
        counts[key] = counts[key] / peak
