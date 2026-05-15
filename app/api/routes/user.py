from fastapi import APIRouter, Depends, HTTPException
import secrets
from datetime import datetime, timezone
from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.schemas.user import APIKeyResponse, APIKeyInfo

router = APIRouter(prefix="/user", tags=["User"])

# Separate /users router for the canonical "current user" surface so existing
# /user/api-key consumers don't break and frontend can call /users/me.
users_router = APIRouter(prefix="/users", tags=["User"])


@users_router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    """Return the authenticated user's public profile.

    Frontend hydrates avatar, role, and admin-only UI from this response.
    """
    quota_limit = current_user.get("quota_limit", 100)
    quota_used = current_user.get("quota_used", 0)
    
    return {
        "username": current_user.get("username"),
        "email": current_user.get("email"),
        "role": current_user.get("role"),
        "is_verified": current_user.get("is_verified", False),
        "auth_provider": current_user.get("auth_provider"),
        "created_at": current_user.get("created_at"),
        "quota": {
            "limit": quota_limit,
            "used": quota_used,
            "remaining": max(0, quota_limit - quota_used),
            "last_reset": current_user.get("last_quota_reset")
        }
    }


@users_router.get("/quota")
async def get_quota(current_user: dict = Depends(get_current_user)):
    """Return the current user's usage quota."""
    quota_limit = current_user.get("quota_limit", 100)
    quota_used = current_user.get("quota_used", 0)
    
    return {
        "limit": quota_limit,
        "used": quota_used,
        "remaining": max(0, quota_limit - quota_used),
        "last_reset": current_user.get("last_quota_reset")
    }


@router.post("/api-key", response_model=APIKeyResponse)
async def generate_api_key(current_user: dict = Depends(get_current_user)):
    """Generate a new personal API key. Overwrites existing one."""
    db = get_db()

    # Generate random 32-char hex string
    api_key = secrets.token_hex(16)

    # Update user in DB
    await db.users.update_one(
        {"_id": current_user["_id"]},
        {
            "$set": {
                "api_key": api_key,
                "api_key_created_at": datetime.now(timezone.utc),
            }
        },
    )

    return APIKeyResponse(api_key=api_key)


@router.get("/api-key", response_model=APIKeyInfo)
async def get_api_key_info(current_user: dict = Depends(get_current_user)):
    """Get information about the current API key (masked)."""
    if "api_key" not in current_user:
        raise HTTPException(status_code=404, detail="No API key found for this user")

    masked = current_user["api_key"][:4] + "*" * 24 + current_user["api_key"][-4:]
    return APIKeyInfo(
        api_key_masked=masked,
        created_at=current_user.get("api_key_created_at", datetime.now(timezone.utc)),
    )


@router.delete("/api-key")
async def revoke_api_key(current_user: dict = Depends(get_current_user)):
    """Revoke the current API key."""
    db = get_db()
    await db.users.update_one(
        {"_id": current_user["_id"]},
        {"$unset": {"api_key": "", "api_key_created_at": ""}},
    )
    return {"message": "API key revoked successfully"}
