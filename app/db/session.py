from motor.motor_asyncio import AsyncIOMotorClient
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)

class Database:
    client: AsyncIOMotorClient = None
    db = None

db_ctx = Database()

# Module-level collection references used by route modules.
# These are None until connect_to_mongo() runs at startup.
papers_collection = None
reports_collection = None
gap_reports_collection = None

async def connect_to_mongo():
    global papers_collection, reports_collection, gap_reports_collection
    try:
        logger.info("Connecting to MongoDB...")
        # Important: specific options to fix SSL and timeout issues as requested
        db_ctx.client = AsyncIOMotorClient(
            settings.MONGODB_URL,
            tls=True,
            tlsAllowInvalidCertificates=True,
            serverSelectionTimeoutMS=30000,
            connectTimeoutMS=30000,
            socketTimeoutMS=30000,
            maxPoolSize=50,
            minPoolSize=5
        )
        db_ctx.db = db_ctx.client[settings.DB_NAME]
        
        # Test connection by running a simple command
        await db_ctx.client.admin.command('ping')
        logger.info("Connected to MongoDB successfully.")

        # Bind module-level collection references so route imports work
        papers_collection = db_ctx.db["papers"]
        reports_collection = db_ctx.db["reports"]
        gap_reports_collection = db_ctx.db["gap_reports"]
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
        raise e

async def close_mongo_connection():
    if db_ctx.client:
        logger.info("Closing MongoDB connection...")
        db_ctx.client.close()
        logger.info("MongoDB connection closed.")

def get_db():
    return db_ctx.db


async def create_indexes():
    """Create database indexes for performance and TTL auto-cleanup.
    
    Called once on application startup. Safe to call multiple times -
    MongoDB will skip indexes that already exist.
    """
    db = get_db()
    if db is None:
        logger.warning("Database not available; skipping index creation.")
        return

    try:
        # --- Users collection ---
        # Unique indexes for fast lookups and constraint enforcement
        await db.users.create_index("username", unique=True)
        await db.users.create_index("email", unique=True)
        # Role index for admin panel filtering
        await db.users.create_index("role")
        logger.info("Created unique indexes on users (username, email) and index on role")

        # --- OTPs collection ---
        # TTL index: automatically deletes the document when current time > expires_at
        # OTPs are set to expire in 5 minutes in auth.py
        await db.otps.create_index("expires_at", expireAfterSeconds=0)
        await db.otps.create_index("email")
        logger.info("Created TTL index on otps.expires_at (5m auto-delete)")

        # --- Reset Tokens collection ---
        # TTL index: automatically deletes the document when current time > expires_at
        # Reset tokens are set to expire in 15 minutes in auth.py
        await db.reset_tokens.create_index("expires_at", expireAfterSeconds=0)
        await db.reset_tokens.create_index("email")
        await db.reset_tokens.create_index("token", unique=True)
        logger.info("Created TTL index on reset_tokens.expires_at (15m auto-delete)")

        # --- Search History collection ---
        await db.search_history.create_index("user_id")
        await db.search_history.create_index("username")
        await db.search_history.create_index("created_at")
        logger.info("Created indexes on search_history.user_id, search_history.username and search_history.created_at")

        # --- Chat History collection ---
        await db.chat_history.create_index("username")
        await db.chat_history.create_index("created_at")
        logger.info("Created indexes on chat_history.username and chat_history.created_at")

        # --- Gap Reports collection ---
        await db.gap_reports.create_index("report_id", unique=True)
        logger.info("Created unique index on gap_reports.report_id")

        logger.info("All database indexes created successfully.")
    except Exception as e:
        logger.error(f"Failed to create indexes: {e}")
        # Don't raise - indexes are optional for functionality, just performance