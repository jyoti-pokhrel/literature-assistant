import logging
import os
from pathlib import Path

import certifi
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient


logger = logging.getLogger(__name__)

ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=ENV_PATH)

MONGO_URL = os.getenv("MONGODB_URL") or os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME", "research_agent")

# Connection settings rationale:
#   maxPoolSize=50            Motor is async; a single uvicorn worker rarely
#                             needs more than ~50 concurrent Mongo ops here
#                             (OLTP REST endpoints — synthesis work is CPU /
#                             external-API bound, not Mongo bound).
#   minPoolSize=5             Pre-warm a small set so first requests skip the
#                             TLS handshake (Atlas handshake is ~100–500ms).
#   maxIdleTimeMS=30_000      Release idle sockets after 30s — Atlas closes
#                             idle connections itself; matching keeps the
#                             client-side view clean.
#   serverSelectionTimeoutMS  Fail fast at 5s instead of the 30s default so a
#                             dead cluster doesn't stall every endpoint.
#   connectTimeoutMS=10_000   Generous budget for Atlas TLS + auth handshake.
#   socketTimeoutMS=20_000    Cap a single stuck op; synthesis pipeline does
#                             not hold one Mongo socket open for long.
#   retryWrites=True          Atlas best practice; safe for idempotent writes.
#   appname                   Surfaces in Atlas server logs for traceability.
CLIENT_OPTIONS: dict = {
    "tlsCAFile": certifi.where(),
    "maxPoolSize": 50,
    "minPoolSize": 5,
    "maxIdleTimeMS": 30_000,
    "serverSelectionTimeoutMS": 5_000,
    "connectTimeoutMS": 10_000,
    "socketTimeoutMS": 20_000,
    "retryWrites": True,
    "appname": "research-agent",
}


def _make_client() -> AsyncIOMotorClient | None:
    if not MONGO_URL:
        return None
    try:
        return AsyncIOMotorClient(MONGO_URL, **CLIENT_OPTIONS)
    except Exception:
        logger.exception("Mongo client init failed with certifi; retrying with permissive TLS")
    try:
        fallback = {**CLIENT_OPTIONS, "tlsAllowInvalidCertificates": True}
        fallback.pop("tlsCAFile", None)
        return AsyncIOMotorClient(MONGO_URL, **fallback)
    except Exception:
        logger.exception("Mongo client init failed in fallback path")
        return None


client = _make_client()
db = client[DB_NAME] if client is not None else None

users_collection = db["users"] if db is not None else None
papers_collection = db["papers"] if db is not None else None
reports_collection = db["reports"] if db is not None else None
gap_reports_collection = db["gap_reports"] if db is not None else None
citation_cache_collection = db["citation_cache"] if db is not None else None
cached_searches_collection = db["cached_searches"] if db is not None else None
projects_collection = db["projects"] if db is not None else None
library_items_collection = db["library_items"] if db is not None else None
feedback_collection = db["feedback"] if db is not None else None
otps_collection = db["otps"] if db is not None else None
reset_tokens_collection = db["reset_tokens"] if db is not None else None
search_history_collection = db["search_history"] if db is not None else None
chat_history_collection = db["chat_history"] if db is not None else None
user_profiles_collection = db["user_profiles"] if db is not None else None
gap_feedback_signals_collection = db["gap_feedback_signals"] if db is not None else None


async def ping() -> bool:
    """Verify the cluster is reachable. Returns False instead of raising."""
    if client is None:
        return False
    try:
        await client.admin.command("ping")
        return True
    except Exception:
        logger.exception("MongoDB ping failed")
        return False


async def _safe_create_index(collection, keys, **kwargs) -> None:
    """Create one index, swallowing conflicts so the rest of init can proceed.

    A pre-existing index with a slightly different spec (e.g. missing the
    `sparse` flag set on an older deployment) raises IndexKeySpecsConflict;
    we log and move on rather than aborting startup.
    """
    if collection is None:
        return
    try:
        await collection.create_index(keys, **kwargs)
    except Exception as exc:
        logger.warning(
            "Skipping index on %s (keys=%s): %s",
            getattr(collection, "name", "<unknown>"),
            keys,
            exc,
        )


async def init_indexes() -> None:
    """Create indexes for collections whose access patterns are owner-scoped.

    Citation-cache indexes are handled separately in services/citations/cache.py
    because that module owns its TTL/expiry semantics.
    """
    if db is None:
        logger.info("MongoDB not configured; skipping index creation")
        return

    # users — match the historical spec (unique, non-sparse) to avoid
    # IndexKeySpecsConflict on clusters that predate this code.
    await _safe_create_index(users_collection, "email", unique=True)
    await _safe_create_index(users_collection, "username", unique=True)

    await _safe_create_index(projects_collection, [("owner", 1), ("updated_at", -1)])
    await _safe_create_index(projects_collection, [("owner", 1), ("archived", 1)])

    await _safe_create_index(
        library_items_collection,
        [("project_id", 1), ("owner", 1), ("source", 1), ("external_id", 1)],
        unique=True,
        name="library_paper_uniq",
    )
    await _safe_create_index(
        library_items_collection,
        [("project_id", 1), ("owner", 1), ("updated_at", -1)],
    )

    await _safe_create_index(reports_collection, [("owner", 1), ("created_at", -1)])
    await _safe_create_index(gap_reports_collection, [("owner", 1), ("created_at", -1)])

    # users — role index used by admin panel filters
    await _safe_create_index(users_collection, "role")

    # OTPs: TTL via expires_at (the document sets expires_at = now + 5min)
    await _safe_create_index(otps_collection, "expires_at", expireAfterSeconds=0)
    await _safe_create_index(otps_collection, "email")

    # Reset tokens: TTL + lookup by token
    await _safe_create_index(reset_tokens_collection, "expires_at", expireAfterSeconds=0)
    await _safe_create_index(reset_tokens_collection, "email")
    await _safe_create_index(reset_tokens_collection, "token", unique=True)

    # Search / chat history
    await _safe_create_index(search_history_collection, "username")
    await _safe_create_index(search_history_collection, "created_at")
    await _safe_create_index(
        search_history_collection, [("username", 1), ("created_at", -1)]
    )
    await _safe_create_index(chat_history_collection, "username")
    await _safe_create_index(chat_history_collection, "created_at")

    # Recommendation system: per-user profile vector + dedup ring buffer
    await _safe_create_index(user_profiles_collection, "username", unique=True)
    await _safe_create_index(user_profiles_collection, "profile_updated_at")

    # Per-user gap-feedback signal log (decoupled from gap_reports because
    # the existing gap_reports docs aren't stamped with an owner).
    await _safe_create_index(
        gap_feedback_signals_collection,
        [("username", 1), ("updated_at", -1)],
    )
    await _safe_create_index(
        gap_feedback_signals_collection,
        [("username", 1), ("report_id", 1), ("gap_id", 1)],
        unique=True,
        name="gap_feedback_signal_uniq",
    )

    # Recommendation candidates: dedup lookup by (source, external_id) and
    # backfill scans over freshly-embedded rows.
    await _safe_create_index(
        papers_collection,
        [("source", 1), ("external_id", 1)],
    )
    await _safe_create_index(papers_collection, "embedded_at", sparse=True)


async def close_db() -> None:
    if client is not None:
        client.close()


def get_db():
    """Return the active Motor database handle (or None if Mongo is not configured)."""
    return db
