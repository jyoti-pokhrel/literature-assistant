"""Compose and cache a per-user profile vector for personalized recommendations.

The profile is a weighted centroid of three signal types:
  * Cold-start seed topics (decays as the user accumulates searches).
  * Recent search topics (exponential half-life ~10 days).
  * Gap-feedback embeddings (positives boost, downvotes subtract).

The vector is L2-normalized and cached on `user_profiles_collection`.
Invalidated by `invalidate()` when new signals are written; the loader
recomputes lazily on the next read.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np

from app.db.session import user_profiles_collection
from app.services.recommendations.embedder import embed_texts
from app.services.recommendations.signals import (
    GapSignal,
    SearchSignal,
    fetch_gap_signals,
    fetch_search_signals,
)
from app.services.recommendations.interactions import (
    INTERACTION_WEIGHTS,
    fetch_interaction_signals,
)

logger = logging.getLogger(__name__)

SEED_WEIGHT = 0.5
SEED_DECAY_THRESHOLD = 5  # searches needed before seeds fully decay
SEARCH_HALF_LIFE_DAYS = 14.0
GAP_POSITIVE_WEIGHT = 1.0
GAP_NEGATIVE_WEIGHT = -0.6
INTERACTION_HALF_LIFE_DAYS = 21.0

SEEN_EXPIRY_DAYS = 21
SEEN_MAX_KEEP = 1000


def _decayed_seen_ids(doc: dict) -> list[str]:
    """Materialize the active seen-paper set from a user_profiles doc.

    Honors the new timestamped `seen_impressions` array (filtered to last
    SEEN_EXPIRY_DAYS) and the legacy bare `seen_paper_ids` list (always
    included — those entries predate the timestamp schema, so we keep them
    until they age out via the ring buffer trim).
    """
    impressions = doc.get("seen_impressions") or []
    cutoff = datetime.now(timezone.utc) - timedelta(days=SEEN_EXPIRY_DAYS)
    ids: list[str] = []
    for entry in impressions:
        if not isinstance(entry, dict):
            continue
        ts = entry.get("ts")
        if isinstance(ts, datetime):
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= cutoff:
                eid = entry.get("id")
                if eid:
                    ids.append(eid)
        else:
            # entries without ts are treated as fresh to avoid forever-block
            eid = entry.get("id")
            if eid:
                ids.append(eid)
    for legacy in (doc.get("seen_paper_ids") or []):
        if legacy:
            ids.append(legacy)
    return ids


@dataclass
class ProfileComponent:
    kind: str
    label: str
    weight: float
    vector: list[float]
    meta: dict = field(default_factory=dict)


@dataclass
class Profile:
    user_id: str
    username: str
    vector: Optional[list[float]]
    seed_topics: list[str]
    components: list[ProfileComponent]
    top_topics: list[str]
    updated_at: datetime
    seen_paper_ids: list[str]

    @property
    def is_cold_start(self) -> bool:
        return self.vector is None


def _search_weight(signal: SearchSignal) -> float:
    now = datetime.now(timezone.utc)
    age = (now - signal.created_at).total_seconds() / 86400.0
    return min(1.0, math.exp(-age / SEARCH_HALF_LIFE_DAYS))


def _gap_weight(signal: GapSignal) -> float:
    if signal.vote == "up" or signal.pursue:
        return GAP_POSITIVE_WEIGHT
    if signal.vote == "down":
        return GAP_NEGATIVE_WEIGHT
    return 0.0


def _interaction_weight(signal) -> float:
    """Decay raw interaction weights over INTERACTION_HALF_LIFE_DAYS."""
    age = (datetime.now(timezone.utc) - signal.ts).total_seconds() / 86400.0
    return signal.weight * min(1.0, math.exp(-age / INTERACTION_HALF_LIFE_DAYS))


async def _embed_signal_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    return await embed_texts(texts)


async def _compose_profile(
    username: str,
    user_id: str,
    seed_topics: list[str],
    seed_vectors: list[list[float]],
    seen_paper_ids: list[str],
) -> Profile:
    search_signals = await fetch_search_signals(username, user_id=user_id)
    gap_signals = await fetch_gap_signals(username, user_id=user_id)

    components: list[ProfileComponent] = []

    seed_decay = max(0.0, 1.0 - len(search_signals) / SEED_DECAY_THRESHOLD)
    if seed_decay > 0:
        for topic, vector in zip(seed_topics, seed_vectors):
            if not vector:
                continue
            components.append(
                ProfileComponent(
                    kind="seed",
                    label=topic,
                    weight=SEED_WEIGHT * seed_decay,
                    vector=vector,
                )
            )

    search_texts = [s.topic for s in search_signals]
    search_vectors = await _embed_signal_texts(search_texts)
    for signal, vector in zip(search_signals, search_vectors):
        components.append(
            ProfileComponent(
                kind="search",
                label=signal.topic,
                weight=_search_weight(signal),
                vector=list(vector),
                meta={"ts": signal.created_at.isoformat()},
            )
        )

    gap_texts = [g.gap_text for g in gap_signals]
    gap_vectors = await _embed_signal_texts(gap_texts)
    for signal, vector in zip(gap_signals, gap_vectors):
        weight = _gap_weight(signal)
        if weight == 0.0:
            continue
        components.append(
            ProfileComponent(
                kind="gap_positive" if weight > 0 else "gap_negative",
                label=signal.gap_title,
                weight=weight,
                vector=list(vector),
                meta={"gap_id": signal.gap_id},
            )
        )

    interaction_signals = await fetch_interaction_signals(username, user_id=user_id)
    for signal in interaction_signals:
        weight = _interaction_weight(signal)
        if weight == 0.0:
            continue
        components.append(
            ProfileComponent(
                kind=(
                    "interaction_positive"
                    if weight > 0
                    else "interaction_negative"
                ),
                label=signal.external_id,
                weight=weight,
                vector=list(signal.embedding),
                meta={"kind": signal.kind, "ts": signal.ts.isoformat()},
            )
        )

    contributing = [c for c in components if c.weight != 0 and c.vector]
    total_weight = sum(abs(c.weight) for c in contributing)
    if total_weight <= 0 or not contributing:
        return Profile(
            user_id=user_id,
            username=username,
            vector=None,
            seed_topics=seed_topics,
            components=[],
            top_topics=[],
            updated_at=datetime.now(timezone.utc),
            seen_paper_ids=seen_paper_ids,
        )

    stacked = np.array([c.vector for c in contributing], dtype=np.float32)
    weights = np.array([c.weight for c in contributing], dtype=np.float32)
    weighted = stacked * weights[:, None]
    centroid = weighted.sum(axis=0) / total_weight
    norm = float(np.linalg.norm(centroid))
    if norm < 1e-6:
        return Profile(
            user_id=user_id,
            username=username,
            vector=None,
            seed_topics=seed_topics,
            components=[],
            top_topics=[],
            updated_at=datetime.now(timezone.utc),
            seen_paper_ids=seen_paper_ids,
        )
    centroid = centroid / norm

    top_topics: list[str] = []
    seen_labels: set[str] = set()
    for component in sorted(contributing, key=lambda c: abs(c.weight), reverse=True):
        if component.weight <= 0:
            continue
        label = component.label.strip().lower()
        if label in seen_labels:
            continue
        seen_labels.add(label)
        top_topics.append(component.label)
        if len(top_topics) >= 5:
            break

    return Profile(
        user_id=user_id,
        username=username,
        vector=centroid.astype(np.float32).tolist(),
        seed_topics=seed_topics,
        components=contributing,
        top_topics=top_topics,
        updated_at=datetime.now(timezone.utc),
        seen_paper_ids=seen_paper_ids,
    )


def _serialize_components(components: list[ProfileComponent]) -> list[dict]:
    return [
        {
            "kind": c.kind,
            "label": c.label,
            "weight": float(c.weight),
            "meta": c.meta,
        }
        for c in components
    ]


async def _persist_profile(profile: Profile) -> None:
    if user_profiles_collection is None:
        return
    update_doc = {
        "$set": {
            "user_id": profile.user_id,
            "username": profile.username,
            "profile_vector": profile.vector,
            "profile_components": _serialize_components(profile.components),
            "top_topics": profile.top_topics,
            "profile_updated_at": profile.updated_at,
        }
    }
    query = {"user_id": profile.user_id} if profile.user_id else {"username": profile.username}
    await user_profiles_collection.update_one(
        query,
        update_doc,
        upsert=True,
    )


async def _load_doc(username: str, user_id: str | None = None) -> dict:
    if user_profiles_collection is None:
        return {}
    query = {"user_id": user_id} if user_id else {"username": username}
    doc = await user_profiles_collection.find_one(query)
    return doc or {}


async def build_profile(username: str, user_id: str | None = None) -> Profile:
    """Recompute and persist the profile vector for `username`."""
    doc = await _load_doc(username, user_id=user_id)
    seed_topics = list(doc.get("seed_topics") or [])
    seed_vectors = [list(v) for v in (doc.get("seed_topic_embeddings") or []) if v]
    seen_paper_ids = _decayed_seen_ids(doc)

    if len(seed_vectors) < len(seed_topics):
        seed_vectors = await embed_texts(seed_topics)
        if user_profiles_collection is not None:
            query = {"user_id": user_id} if user_id else {"username": username}
            await user_profiles_collection.update_one(
                query,
                {"$set": {"seed_topic_embeddings": seed_vectors}},
                upsert=True,
            )
    
    # Ensure we have a user_id for the Profile object even if the doc didn't have it
    effective_user_id = user_id or doc.get("user_id") or ""

    profile = await _compose_profile(username, effective_user_id, seed_topics, seed_vectors, seen_paper_ids)
    await _persist_profile(profile)
    return profile


async def load_profile(username: str, user_id: str | None = None) -> Profile:
    """Return cached profile if fresh; otherwise rebuild.
 
    A cached vector is considered stale when `dirty: True` is set on the doc.
    """
    doc = await _load_doc(username, user_id=user_id)
    effective_user_id = user_id or doc.get("user_id") or ""
    seed_topics = list(doc.get("seed_topics") or [])
    seen_paper_ids = _decayed_seen_ids(doc)
    vector = doc.get("profile_vector")
    is_dirty = bool(doc.get("dirty"))

    if not is_dirty and vector and doc.get("profile_components") is not None:
        components = [
            ProfileComponent(
                kind=item.get("kind", ""),
                label=item.get("label", ""),
                weight=float(item.get("weight", 0.0)),
                vector=[],
                meta=item.get("meta") or {},
            )
            for item in (doc.get("profile_components") or [])
        ]
        return Profile(
            user_id=effective_user_id,
            username=username,
            vector=list(vector),
            seed_topics=seed_topics,
            components=components,
            top_topics=list(doc.get("top_topics") or []),
            updated_at=doc.get("profile_updated_at") or datetime.now(timezone.utc),
            seen_paper_ids=seen_paper_ids,
        )
 
    profile = await build_profile(username, user_id=user_id)
    if user_profiles_collection is not None and is_dirty:
        query = {"user_id": user_id} if user_id else {"username": username}
        await user_profiles_collection.update_one(
            query,
            {"$unset": {"dirty": ""}},
        )
    return profile


async def set_seed_topics(username: str, topics: list[str], user_id: str | None = None) -> Profile:
    """Save the 3 cold-start topics and compute the initial profile."""
    cleaned = [t.strip() for t in topics if t and t.strip()]
    seed_vectors = await embed_texts(cleaned)
    if user_profiles_collection is not None:
        query = {"user_id": user_id} if user_id else {"username": username}
        await user_profiles_collection.update_one(
            query,
            {
                "$set": {
                    "user_id": user_id,
                    "username": username,
                    "seed_topics": cleaned,
                    "seed_topic_embeddings": seed_vectors,
                }
            },
            upsert=True,
        )
    return await build_profile(username, user_id=user_id)


async def invalidate(username: str, user_id: str | None = None) -> None:
    """Mark the profile stale so the next load rebuilds it."""
    if user_profiles_collection is None or (not username and not user_id):
        return
    try:
        query = {"user_id": user_id} if user_id else {"username": username}
        await user_profiles_collection.update_one(
            query,
            {"$set": {"dirty": True}},
            upsert=True,
        )
    except Exception:
        logger.exception("Failed to invalidate profile for %s", username)


async def record_impressions(
    username: str, external_ids: list[str], user_id: str | None = None, max_keep: int = SEEN_MAX_KEEP
) -> None:
    """Append timestamped impressions; trim to `max_keep`.
 
    Stores `seen_impressions = [{id, ts}, ...]` rather than a bare id list so
    `load_profile` can filter out impressions older than SEEN_EXPIRY_DAYS,
    letting old papers resurface.
    """
    if user_profiles_collection is None or (not username and not user_id) or not external_ids:
        return
    now = datetime.now(timezone.utc)
    entries = [{"id": eid, "ts": now} for eid in external_ids if eid]
    if not entries:
        return
    try:
        query = {"user_id": user_id} if user_id else {"username": username}
        await user_profiles_collection.update_one(
            query,
            {
                "$push": {
                    "seen_impressions": {
                        "$each": entries,
                        "$slice": -max_keep,
                    }
                },
                "$set": {
                    "user_id": user_id,
                    "username": username,
                    "seen_impressions_updated_at": now
                },
            },
            upsert=True,
        )
    except Exception:
        logger.exception("Failed to record impressions for %s", username)
