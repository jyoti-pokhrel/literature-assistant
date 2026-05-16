import logging
from datetime import datetime, timezone
from typing import Optional, Any
from app.db.session import db

logger = logging.getLogger(__name__)

async def log_activity(
    user_id: Optional[str] = None,
    username: Optional[str] = None,
    action: str = "",
    details: Optional[Any] = None,
    activity_type: str = "general"
):
    """
    Logs an activity to the database.
    activity_type: 'login', 'search', 'admin_action', 'report_gen', 'system'
    """
    if db is None:
        return

    try:
        activity = {
            "user_id": user_id,
            "username": username,
            "action": action,
            "details": details,
            "type": activity_type,
            "created_at": datetime.now(timezone.utc)
        }
        await db.activities.insert_one(activity)
    except Exception:
        logger.exception("Failed to log activity")

async def get_recent_activities(limit: int = 50, skip: int = 0):
    if db is None:
        return []
    
    cursor = db.activities.find().sort("created_at", -1).skip(skip).limit(limit)
    activities = []
    async for act in cursor:
        act["_id"] = str(act["_id"])
        activities.append(act)
    return activities
