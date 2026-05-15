import logging
from datetime import datetime, timezone
from app.db.session import get_db

logger = logging.getLogger(__name__)

async def save_search_history(username: str, query_text: str, filters: dict, results_count: int = 0, report_id: str = None, user_id: str = None):
    """Internal helper to save search history to MongoDB with user isolation."""
    try:
        db = get_db()
        if db is None:
            logger.warning("Database not available; skipping search history save.")
            return
            
        now = datetime.now(timezone.utc)
        
        # Build filter for finding existing records
        search_filter = {
            "query": query_text,
            "filters": filters
        }
        if user_id:
            search_filter["user_id"] = user_id
        else:
            search_filter["username"] = username

        existing = await db.search_history.find_one(search_filter)

        if existing:
            await db.search_history.update_one(
                {"_id": existing["_id"]},
                {"$set": {
                    "created_at": now,
                    "result_count": results_count, # Use consistent field name
                    "report_id": report_id or existing.get("report_id"),
                    "user_id": user_id or existing.get("user_id"),
                    "username": username # Keep username for backwards compatibility
                }}
            )
            logger.info(f"Updated search history for user {username}: {query_text}")
        else:
            search_item = {
                "user_id": user_id,
                "username": username,
                "query": query_text,
                "filters": filters,
                "result_count": results_count,
                "report_id": report_id,
                "created_at": now
            }
            await db.search_history.insert_one(search_item)
            logger.info(f"Saved search history for user {username}: {query_text} (Report: {report_id})")
    except Exception as e:
        logger.error(f"Failed to save search history: {e}")
