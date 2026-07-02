from fastapi import APIRouter, Depends, HTTPException, Query
from datetime import datetime, timedelta, timezone
from typing import Optional

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


from pydantic import BaseModel, EmailStr, Field

class AdminUserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=20, pattern=r"^[a-zA-Z0-9_-]+$")
    email: EmailStr
    password: str = Field(..., min_length=8)
    role: str = "admin"


@router.post("/users")
async def create_user_by_system(
    data: AdminUserCreate, admin: dict = Depends(get_current_admin)
):
    """Directly create a user with a specific role, accessible only to System User."""
    if admin.get("role") != "system_user":
        raise HTTPException(
            status_code=403,
            detail="Permission Denied: Access restricted to System User."
        )
        
    db = get_db()
    
    # Check if username or email already exists
    existing = await db.users.find_one({
        "$or": [{"username": data.username}, {"email": data.email}]
    })
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Username or email already registered"
        )
        
    from app.core.security import get_password_hash
    hashed_password = get_password_hash(data.password)
    
    user_doc = {
        "username": data.username,
        "email": data.email,
        "password": hashed_password,
        "is_verified": True,
        "is_active": True,
        "auth_provider": "local",
        "role": data.role,
        "created_at": datetime.now(timezone.utc),
        "quota_limit": 100 if data.role not in {"admin", "system_user"} else 9999,
        "quota_used": 0,
        "last_quota_reset": datetime.now(timezone.utc),
    }
    
    await db.users.insert_one(user_doc)
    
    await log_activity(
        user_id=str(admin["_id"]),
        username=admin["username"],
        action=f"System User created account {data.username} with role {data.role}",
        activity_type="admin_action"
    )
    
    return {"message": f"User {data.username} created successfully with role {data.role}"}


@router.get("/system-dashboard-stats")
async def get_system_dashboard_stats(admin: dict = Depends(get_current_admin)):
    """Get advanced system stats, accessible only to the System User."""
    if admin.get("role") != "system_user":
        raise HTTPException(
            status_code=403,
            detail="Permission Denied: Access restricted to System User."
        )
    
    db = get_db()
    
    # Retrieve all admins in the system
    cursor = db.users.find({"role": "admin"}, {"password": 0})
    admins_list = []
    async for u in cursor:
        u["_id"] = str(u["_id"])
        admins_list.append(u)
        
    # Get count of admins
    admin_count = len(admins_list)
    
    health = {
        "status": "healthy" if db is not None else "unhealthy",
        "database": "MongoDB Connected",
        "admin_count": admin_count,
        "system_user_protected": True
    }
    
    return {
        "admins": admins_list,
        "health": health
    }


@router.patch("/users/{username}")
async def update_user(
    username: str, data: UserUpdate, admin: dict = Depends(get_current_admin)
):
    """Update a user's role, quota, or status."""
    db = get_db()
    
    target_user = await db.users.find_one({"username": username})
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = {k: v for k, v in data.dict().items() if v is not None}
    if not update_data:
        raise HTTPException(status_code=400, detail="No update data provided")

    current_role = admin.get("role")
    target_role = target_user.get("role")
    target_username = target_user.get("username")

    is_target_system = (target_role == "system_user" or target_username == "Sachu")
    
    if is_target_system:
        if "is_active" in update_data and update_data["is_active"] is False:
            raise HTTPException(status_code=403, detail="Permission Denied: System User accounts cannot be deactivated.")
        if "role" in update_data and update_data["role"] != "system_user":
            raise HTTPException(status_code=403, detail="Permission Denied: System User role cannot be changed.")
        if current_role != "system_user":
            raise HTTPException(status_code=403, detail="Permission Denied: Admins cannot edit System User accounts.")

    if target_role == "admin" and current_role == "admin":
        raise HTTPException(status_code=403, detail="Permission Denied: Admins cannot edit other Admin accounts.")

    new_role = update_data.get("role")
    if new_role:
        if new_role in {"admin", "system_user"} and current_role != "system_user":
            raise HTTPException(status_code=403, detail="Permission Denied: Only the System User can promote users to Admin or System User roles.")
        if target_role == "admin" and new_role != "admin" and current_role != "system_user":
            raise HTTPException(status_code=403, detail="Permission Denied: Only the System User can demote Admin accounts.")

    result = await db.users.update_one({"username": username}, {"$set": update_data})

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
    
    target_user = await db.users.find_one({"username": username})
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    target_role = target_user.get("role")
    target_username = target_user.get("username")
    current_role = admin.get("role")

    if target_role == "system_user" or target_username == "Sachu":
        raise HTTPException(status_code=403, detail="Permission Denied: The System User account cannot be deleted.")

    if target_role == "admin" and current_role == "admin":
        raise HTTPException(status_code=403, detail="Permission Denied: Admins cannot delete other Admin accounts.")

    result = await db.users.delete_one({"username": username})

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
