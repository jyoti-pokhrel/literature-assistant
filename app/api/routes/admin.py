from fastapi import APIRouter, Depends
from datetime import datetime, timedelta, timezone

from app.api.dependencies import get_current_admin
from app.db.session import get_db

from app.schemas.user import UserUpdate

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users")
async def get_all_users(
    limit: int = 100, skip: int = 0, admin: dict = Depends(get_current_admin)
):
    """Get all registered users. Only accessible by admins."""
    db = get_db()
    cursor = (
        db.users.find({}, {"password": 0})
        .sort("created_at", -1)
        .skip(skip)
        .limit(limit)
    )
    users = []
    async for user in cursor:
        user["_id"] = str(user["_id"])
        users.append(user)
    return users


@router.patch("/users/{username}")
async def update_user(
    username: str, data: UserUpdate, admin: dict = Depends(get_current_admin)
):
    """Update a user's role or quota. Only accessible by admins."""
    db = get_db()
    update_data = {k: v for k, v in data.dict().items() if v is not None}

    if not update_data:
        raise HTTPException(status_code=400, detail="No update data provided")

    result = await db.users.update_one({"username": username}, {"$set": update_data})

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")

    return {"message": "User updated successfully", "updated": update_data}


@router.get("/stats")
async def get_system_stats(admin: dict = Depends(get_current_admin)):
    """Get system usage statistics. Only accessible by admins."""
    db = get_db()

    # User stats
    total_users = await db.users.count_documents({})
    verified_users = await db.users.count_documents({"is_verified": True})
    google_users = await db.users.count_documents({"auth_provider": "google"})

    # Activity stats
    total_searches = await db.search_history.count_documents({})
    total_reports = await db.gap_reports.count_documents({})

    # Recent activity (last 24 hours)
    last_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    new_users_24h = await db.users.count_documents({"created_at": {"$gte": last_24h}})
    searches_24h = await db.search_history.count_documents(
        {"created_at": {"$gte": last_24h}}
    )

    return {
        "users": {
            "total": total_users,
            "verified": verified_users,
            "local": total_users - google_users,
            "google": google_users,
            "new_last_24h": new_users_24h,
        },
        "usage": {
            "total_searches": total_searches,
            "total_reports": total_reports,
            "searches_last_24h": searches_24h,
        },
        "system": {"status": "healthy", "db_connected": db is not None},
    }
