import logging
from datetime import datetime, timezone
from app.db.session import get_db

logger = logging.getLogger(__name__)

async def save_search_history(username: str, topic: str, filters: dict, results_count: int = 0, report_id: str = None):
    """Internal helper to save search history to MongoDB."""
    try:
        db = get_db()
        if db is None:
            logger.warning("Database not available; skipping search history save.")
            return
            
        now = datetime.now(timezone.utc)
        
        # Check for existing identical search to avoid duplicates
        existing = await db.search_history.find_one({
            "username": username,
            "topic": topic,
            "filters": filters
        })

        if existing:
            await db.search_history.update_one(
                {"_id": existing["_id"]},
                {"$set": {
                    "created_at": now,
                    "results_count": results_count,
                    "report_id": report_id or existing.get("report_id")
                }}
            )
            logger.info(f"Updated search history for user {username}: {topic}")
        else:
            search_item = {
                "username": username,
                "topic": topic,
                "filters": filters,
                "results_count": results_count,
                "report_id": report_id,
                "created_at": now
            }
            await db.search_history.insert_one(search_item)
            logger.info(f"Saved search history for user {username}: {topic} (Report: {report_id})")
    except Exception as e:
        logger.error(f"Failed to save search history: {e}")
