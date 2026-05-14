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

# Optimized connection settings for Atlas
CLIENT_OPTIONS: dict = {
    "maxPoolSize": 50,
    "minPoolSize": 5,
    "maxIdleTimeMS": 30_000,
    "serverSelectionTimeoutMS": 30_000,
    "connectTimeoutMS": 30_000,
    "socketTimeoutMS": 20_000,
    "retryWrites": True,
    "appname": "research-agent",
    "tlsCAFile": certifi.where(),
}


def _make_client() -> AsyncIOMotorClient | None:
    if not MONGO_URL:
        return None
    try:
        return AsyncIOMotorClient(MONGO_URL, **CLIENT_OPTIONS)
    except Exception:
        logger.exception("Mongo client init failed")
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
paper_interactions_collection = db["paper_interactions"] if db is not None else None


async def ping() -> bool:
    if client is None:
        return False
    try:
        await client.admin.command("ping")
        return True
    except Exception:
        logger.exception("MongoDB ping failed")
        return False


async def _safe_create_index(collection, keys, **kwargs) -> None:
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
    if db is None:
        return

    # Core indexes
    await _safe_create_index(users_collection, "email", unique=True)
    await _safe_create_index(users_collection, "username", unique=True)
    await _safe_create_index(otps_collection, "expires_at", expireAfterSeconds=0)
    await _safe_create_index(reset_tokens_collection, "expires_at", expireAfterSeconds=0)
    
    # History and Profile indexes
    await _safe_create_index(search_history_collection, "user_id")
    await _safe_create_index(search_history_collection, "created_at")
    await _safe_create_index(chat_history_collection, "user_id")
    await _safe_create_index(user_profiles_collection, "user_id", unique=True)


async def close_db() -> None:
    if client is not None:
        client.close()


def get_db():
    return db
