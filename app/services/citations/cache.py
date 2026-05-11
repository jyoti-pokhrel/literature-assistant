from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional, Tuple

from app.db.session import citation_cache_collection


logger = logging.getLogger(__name__)


TTL_DAYS = 30
# Cap any Mongo round-trip so a dead Atlas cluster cannot stall the citation build.
CACHE_OP_TIMEOUT_SECONDS = 2.0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _strip_mongo(doc: dict) -> dict:
    """Drop Mongo-only keys before handing a document to callers."""
    doc.pop("_id", None)
    return doc


async def ensure_indexes() -> None:
    if citation_cache_collection is None:
        logger.info("citation_cache_collection is not configured; skipping index creation")
        return
    try:
        await asyncio.wait_for(
            citation_cache_collection.create_index("expires_at", expireAfterSeconds=0),
            timeout=CACHE_OP_TIMEOUT_SECONDS,
        )
        await asyncio.wait_for(
            citation_cache_collection.create_index("paper_id", unique=True),
            timeout=CACHE_OP_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.warning("citation_cache index creation failed; cache will run without indexes")


async def get_cached(paper_id: str) -> Optional[dict]:
    if citation_cache_collection is None or not paper_id:
        return None
    try:
        doc = await asyncio.wait_for(
            citation_cache_collection.find_one({"_id": paper_id}),
            timeout=CACHE_OP_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("citation_cache get_cached timed out after %.1fs; treating as miss", CACHE_OP_TIMEOUT_SECONDS)
        return None
    except Exception:
        logger.warning("citation_cache get_cached failed; treating as miss")
        return None
    if doc is None:
        return None
    expires_at = doc.get("expires_at")
    if isinstance(expires_at, datetime) and expires_at <= _utcnow():
        return None
    return _strip_mongo(doc)


async def put_cached(
    paper_id: str,
    payload: dict,
    *,
    seed_meta: Optional[dict] = None,
) -> None:
    if citation_cache_collection is None or not paper_id:
        return
    now = _utcnow()
    document = {
        "_id": paper_id,
        "paper_id": paper_id,
        "hop1": payload,
        "seed_meta": seed_meta or {},
        "fetched_at": now,
        "expires_at": now + timedelta(days=TTL_DAYS),
    }
    try:
        await asyncio.wait_for(
            citation_cache_collection.replace_one({"_id": paper_id}, document, upsert=True),
            timeout=CACHE_OP_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("citation_cache put_cached timed out after %.1fs; skipping write", CACHE_OP_TIMEOUT_SECONDS)
    except Exception:
        logger.warning("citation_cache put_cached failed; skipping write")


async def get_or_set(
    paper_id: str,
    build: Callable[[], Awaitable[dict]],
    *,
    seed_meta_provider: Optional[Callable[[dict], dict]] = None,
) -> Tuple[dict, bool]:
    """Return (hop1_payload, was_hit). On miss, runs `build()` and writes through."""
    cached = await get_cached(paper_id)
    if cached is not None:
        return cached.get("hop1", {}), True
    payload = await build()
    seed_meta = seed_meta_provider(payload) if seed_meta_provider else None
    await put_cached(paper_id, payload, seed_meta=seed_meta)
    return payload, False
