import os
import ssl
from pathlib import Path
import certifi

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient


ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=ENV_PATH)

MONGO_URL = os.getenv("MONGODB_URL") or os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME", "research_agent")


def _make_client() -> AsyncIOMotorClient | None:
    if not MONGO_URL:
        return None
    try:
        # Preferred: certifi CA bundle (most reliable on Windows)
        return AsyncIOMotorClient(
            MONGO_URL,
            tls=True,
            tlsCAFile=certifi.where(),
            tlsAllowInvalidCertificates=True,
            serverSelectionTimeoutMS=10_000,
        )
    except Exception:
        pass
    try:
        # Fallback: system SSL context, no hostname check (handles some Atlas TLS issues)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return AsyncIOMotorClient(
            MONGO_URL,
            tls=True,
            tlsAllowInvalidCertificates=True,
            serverSelectionTimeoutMS=10_000,
        )
    except Exception:
        return None


client = _make_client()
db = client[DB_NAME] if client is not None else None

users_collection      = db["users"]       if db is not None else None
papers_collection     = db["papers"]      if db is not None else None
reports_collection    = db["reports"]     if db is not None else None
gap_reports_collection = db["gap_reports"] if db is not None else None
citation_cache_collection = db["citation_cache"] if db is not None else None
cached_searches_collection = db["cached_searches"] if db is not None else None
