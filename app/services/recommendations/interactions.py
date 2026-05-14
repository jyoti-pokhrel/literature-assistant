"""Per-user paper-interaction log for the explore feed.

Records every explicit per-card action (`open`, `like`, `save`, `dislike`,
`hide`) into `paper_interactions_collection`. The dedup index makes each
(user, paper, kind) record at-most-once — re-firing the same action just
refreshes `ts`.

`fetch_interaction_signals` powers the new signal source in
`profile_builder`. Embedding lookup is done from `papers_collection`
because the candidate paper has already been embedded for vector search.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.db.session import paper_interactions_collection, papers_collection

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 30
SIGNAL_LIMIT = 200

INTERACTION_WEIGHTS: dict[str, float] = {
    "open": 0.3,
    "like": 1.0,
    "save": 1.0,
    "dislike": -0.8,
    "hide": -0.5,
}


@dataclass
class InteractionSignal:
    external_id: str
    kind: str
    weight: float
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    embedding: list[float] = field(default_factory=list)


def _weight_for(kind) -> float:
    if not isinstance(kind, str):
        return 0.0
    return INTERACTION_WEIGHTS.get(kind, 0.0)


async def record_interaction(username: str, external_id: str, kind: str) -> None:
    """Upsert one (user, paper, kind) row. Refreshes `ts` on re-fire."""
    if paper_interactions_collection is None or not username or not external_id:
        return
    if kind not in INTERACTION_WEIGHTS:
        return
    now = datetime.now(timezone.utc)
    try:
        await paper_interactions_collection.update_one(
            {"username": username, "external_id": external_id, "kind": kind},
            {
                "$set": {
                    "username": username,
                    "external_id": external_id,
                    "kind": kind,
                    "ts": now,
                }
            },
            upsert=True,
        )
    except Exception:
        logger.exception(
            "Failed to record interaction %s for %s on %s",
            kind,
            username,
            external_id,
        )


async def fetch_interaction_signals(username: str) -> list[InteractionSignal]:
    """Materialize the interaction signal list for the profile builder.

    Joins each interaction with the paper's stored embedding so the profile
    centroid can include it without re-embedding text. Interactions whose
    paper carries no embedding are skipped — they will contribute on the
    next call after embedding catches up.
    """
    if paper_interactions_collection is None or papers_collection is None:
        return []
    if not username:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    try:
        cursor = (
            paper_interactions_collection.find(
                {"username": username, "ts": {"$gte": cutoff}},
                projection={"external_id": 1, "kind": 1, "ts": 1},
            )
            .sort("ts", -1)
            .limit(SIGNAL_LIMIT)
        )
        rows = [doc async for doc in cursor]
    except Exception:
        logger.exception("Failed to load interactions for %s", username)
        return []

    if not rows:
        return []

    external_ids = list({r.get("external_id") for r in rows if r.get("external_id")})
    embeddings_by_id: dict[str, list[float]] = {}
    try:
        cursor = papers_collection.find(
            {"external_id": {"$in": external_ids}, "embedding": {"$exists": True}},
            projection={"external_id": 1, "embedding": 1},
        )
        async for doc in cursor:
            eid = doc.get("external_id")
            emb = doc.get("embedding")
            if eid and isinstance(emb, list) and emb:
                embeddings_by_id[eid] = emb
    except Exception:
        logger.exception("Failed to load embeddings for interactions of %s", username)
        return []

    signals: list[InteractionSignal] = []
    for row in rows:
        eid = row.get("external_id")
        kind = row.get("kind")
        weight = _weight_for(kind)
        if weight == 0.0 or not eid:
            continue
        emb = embeddings_by_id.get(eid)
        if not emb:
            continue
        ts = row.get("ts")
        if not isinstance(ts, datetime):
            ts = datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        signals.append(
            InteractionSignal(
                external_id=eid, kind=kind, weight=weight, ts=ts, embedding=emb
            )
        )
    return signals
