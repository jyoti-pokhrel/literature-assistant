from fastapi import APIRouter, Depends, HTTPException, Query
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from bson import ObjectId

from app.api.dependencies import get_current_admin
from app.db.session import get_db
from app.schemas.user import UserUpdate
from app.utils.activity import log_activity, get_recent_activities

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users")
async def get_all_users(
    limit: int = Query(50, ge=1, le=100),
    skip: int = Query(0, ge=0),
    role: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    admin: dict = Depends(get_current_admin)
):
    """Get all registered users with filtering and pagination."""
    db = get_db()
    query = {}
    
    if role:
        query["role"] = role
    if status == "verified":
        query["is_verified"] = True
    elif status == "pending":
        query["is_verified"] = False
    elif status == "banned":
        query["is_active"] = False
    
    if search:
        query["$or"] = [
            {"username": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}}
        ]

    total_count = await db.users.count_documents(query)
    
    cursor = (
        db.users.find(query, {"password": 0})
        .sort("created_at", -1)
        .skip(skip)
        .limit(limit)
    )
    
    users = []
    async for user in cursor:
        user["_id"] = str(user["_id"])
        users.append(user)
        
    return {
        "total": total_count,
        "users": users,
        "limit": limit,
        "skip": skip
    }


@router.patch("/users/{username}")
async def update_user(
    username: str, data: UserUpdate, admin: dict = Depends(get_current_admin)
):
    """Update a user's role, quota, or status."""
    db = get_db()
    update_data = {k: v for k, v in data.dict().items() if v is not None}

    if not update_data:
        raise HTTPException(status_code=400, detail="No update data provided")

    result = await db.users.update_one({"username": username}, {"$set": update_data})

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")

    await log_activity(
        user_id=str(admin["_id"]),
        username=admin["username"],
        action=f"Admin updated user {username}",
        details=update_data,
        activity_type="admin_action"
    )

    return {"message": "User updated successfully", "updated": update_data}


@router.delete("/users/{username}")
async def delete_user(username: str, admin: dict = Depends(get_current_admin)):
    """Delete a user account."""
    db = get_db()
    result = await db.users.delete_one({"username": username})
    
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="User not found")

    await log_activity(
        user_id=str(admin["_id"]),
        username=admin["username"],
        action=f"Admin deleted user {username}",
        activity_type="admin_action"
    )
    
    return {"message": "User deleted successfully"}


@router.get("/users/{username}/history")
async def get_user_search_history(username: str, admin: dict = Depends(get_current_admin)):
    """View a specific user's search history."""
    db = get_db()
    user = await db.users.find_one({"username": username})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    cursor = db.search_history.find({"user_id": str(user["_id"])}).sort("created_at", -1).limit(100)
    history = []
    async for item in cursor:
        item["_id"] = str(item["_id"])
        history.append(item)
    return history


@router.get("/activities")
async def get_admin_activities(
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
    admin: dict = Depends(get_current_admin)
):
    """Get recent system-wide activities."""
    activities = await get_recent_activities(limit=limit, skip=skip)
    return activities


@router.get("/analytics/searches")
async def get_search_analytics(admin: dict = Depends(get_current_admin)):
    """Get search volume trends for the last 7 days."""
    db = get_db()
    pipeline = [
        {
            "$match": {
                "created_at": {"$gte": datetime.now(timezone.utc) - timedelta(days=7)}
            }
        },
        {
            "$group": {
                "_id": {
                    "$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}
                },
                "count": {"$sum": 1}
            }
        },
        {"$sort": {"_id": 1}}
    ]
    
    results = await db.search_history.aggregate(pipeline).to_list(length=7)
    return results


@router.get("/analytics/trending")
async def get_trending_topics(admin: dict = Depends(get_current_admin)):
    """Get most frequent search topics."""
    db = get_db()
    pipeline = [
        # Project to normalize topic/query field and filter out empty ones
        {
            "$project": {
                "topic": {"$ifNull": ["$topic", "$query"]}
            }
        },
        # Match only documents with a non-empty topic
        {
            "$match": {
                "topic": {"$ne": None, "$not": {"$regex": "^\\s*$"}}
            }
        },
        {"$group": {"_id": "$topic", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10}
    ]
    results = await db.search_history.aggregate(pipeline).to_list(length=10)
    return results


@router.get("/stats")
async def get_system_stats(admin: dict = Depends(get_current_admin)):
    """Get detailed system usage statistics."""
    db = get_db()
    
    start_time = datetime.now(timezone.utc)
    # Simple ping to check latency
    await db.command("ping")
    end_time = datetime.now(timezone.utc)
    latency_ms = int((end_time - start_time).total_seconds() * 1000)

    total_users = await db.users.count_documents({})
    verified_users = await db.users.count_documents({"is_verified": True})
    
    total_searches = await db.search_history.count_documents({})
    total_reports = await db.gap_reports.count_documents({})
    total_papers = await db.papers.count_documents({})

    last_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    new_users_24h = await db.users.count_documents({"created_at": {"$gte": last_24h}})
    searches_24h = await db.search_history.count_documents(
        {"created_at": {"$gte": last_24h}}
    )

    return {
        "users": {
            "total": total_users,
            "verified": verified_users,
            "new_last_24h": new_users_24h,
        },
        "usage": {
            "total_searches": total_searches,
            "total_reports": total_reports,
            "total_papers": total_papers,
            "searches_last_24h": searches_24h,
        },
        "system": {
            "status": "healthy" if db is not None else "degraded",
            "db_connected": db is not None,
            "uptime_days": 1.2,  # Mocked but could be tracked in main.py
            "latency_ms": latency_ms
        },
    }
