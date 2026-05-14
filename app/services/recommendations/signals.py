"""Reads the per-user signal log used to compose a recommendation profile.

Two sources are consulted:
  * `search_history_collection` — last 30 days of topics the user searched.
  * `gap_feedback_signals_collection` — per-user log written from
    feedback.upsert_gap_feedback. Decoupled from gap_reports because reports
    themselves are not stamped with an owner today.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.db.session import (
    gap_feedback_signals_collection,
    search_history_collection,
)


SEARCH_WINDOW_DAYS = 30
SEARCH_LIMIT = 50
GAP_SIGNAL_LIMIT = 50


@dataclass
class SearchSignal:
    topic: str
    created_at: datetime


@dataclass
class GapSignal:
    gap_id: str
    gap_title: str
    gap_text: str
    vote: str | None
    pursue: bool


async def fetch_search_signals(username: str, user_id: str | None = None) -> list[SearchSignal]:
    if search_history_collection is None or (not username and not user_id):
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=SEARCH_WINDOW_DAYS)
    
    # Filter by user_id primarily, fallback to username
    query_filter: dict = {"created_at": {"$gte": cutoff}}
    if user_id:
        query_filter["user_id"] = user_id
    else:
        query_filter["username"] = username

    cursor = (
        search_history_collection.find(
            query_filter,
            projection={"topic": 1, "query": 1, "created_at": 1},
        )
        .sort("created_at", -1)
        .limit(SEARCH_LIMIT)
    )
    results: list[SearchSignal] = []
    async for doc in cursor:
        # Support both new 'query' and legacy 'topic' field names
        topic = (doc.get("query") or doc.get("topic") or "").strip()
        created_at = doc.get("created_at")
        if not topic or not isinstance(created_at, datetime):
            continue
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        results.append(SearchSignal(topic=topic, created_at=created_at))
    return results


async def fetch_gap_signals(username: str, user_id: str | None = None) -> list[GapSignal]:
    if gap_feedback_signals_collection is None or (not username and not user_id):
        return []
    
    query_filter: dict = {}
    if user_id:
        query_filter["user_id"] = user_id
    else:
        query_filter["username"] = username

    cursor = (
        gap_feedback_signals_collection.find(query_filter)
        .sort("updated_at", -1)
        .limit(GAP_SIGNAL_LIMIT)
    )
    results: list[GapSignal] = []
    async for doc in cursor:
        gap_id = str(doc.get("gap_id") or "")
        if not gap_id:
            continue
        title = (doc.get("gap_title") or "").strip()
        description = (doc.get("gap_description") or "").strip()
        gap_text = ". ".join(part for part in (title, description) if part) or title or description
        if not gap_text:
            continue
        results.append(
            GapSignal(
                gap_id=gap_id,
                gap_title=title or "(untitled gap)",
                gap_text=gap_text,
                vote=doc.get("vote"),
                pursue=bool(doc.get("pursue")),
            )
        )
    return results
