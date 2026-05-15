from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.core.config import settings
from app.core.security import decode_access_token
from app.db.session import users_collection

# auto_error=False so requests without an Authorization header still reach the
# function (we want to support dev bypass / API-key fallback).
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login", auto_error=False)


async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    x_api_key: Optional[str] = Header(default=None),
):
    """Resolve the current user via JWT, then API key, then optional dev bypass.

    Dev bypass: when AUTH_DEV_BYPASS=1 in the environment AND no credentials are
    presented, return a synthetic admin user. This preserves the localhost
    workflow documented in CLAUDE.md while letting real tokens take precedence.
    """
    user = None

    if token:
        payload = decode_access_token(token)
        if payload:
            username = payload.get("sub")
            if username and users_collection is not None:
                user = await users_collection.find_one({"username": username})

    if not user and x_api_key and users_collection is not None:
        user = await users_collection.find_one({"api_key": x_api_key})

    if not user:
        if settings.AUTH_DEV_BYPASS and not token and not x_api_key:
            return {
                "username": "local-test-user",
                "role": "admin",
                "is_verified": True,
                "quota_limit": 9999,
                "quota_used": 0,
            }
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Enforce verification
    if not user.get("is_verified"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified. Please verify your email to access this resource.",
        )

    # Initialize quotas if missing (Migration path for existing users)
    needs_update = False
    update_data = {}

    if "quota_limit" not in user:
        update_data["quota_limit"] = settings.DEFAULT_QUOTA_LIMIT
        user["quota_limit"] = settings.DEFAULT_QUOTA_LIMIT
        needs_update = True

    if "quota_used" not in user:
        update_data["quota_used"] = 0
        user["quota_used"] = 0
        needs_update = True

    if "role" not in user:
        update_data["role"] = "researcher"
        user["role"] = "researcher"
        needs_update = True

    if needs_update and users_collection is not None:
        await users_collection.update_one({"_id": user["_id"]}, {"$set": update_data})

    return user


async def get_optional_user(
    token: Optional[str] = Depends(oauth2_scheme),
    x_api_key: Optional[str] = Header(default=None),
):
    """Like get_current_user, but returns None when no credentials are
    provided instead of raising 401. Use for endpoints that work for both
    authenticated and anonymous callers (read-only public-ish surfaces)."""
    if not token and not x_api_key:
        if settings.AUTH_DEV_BYPASS:
            return {
                "username": "local-test-user",
                "role": "admin",
                "is_verified": True,
                "quota_limit": 9999,
                "quota_used": 0,
            }
        return None
    try:
        return await get_current_user(token=token, x_api_key=x_api_key)
    except HTTPException:
        return None


async def check_quota(current_user: dict = Depends(get_current_user)):
    """Dependency to check and increment user quota."""
    if current_user.get("role") == "admin":
        return current_user

    # Reset quota if it's a new day
    last_reset = current_user.get("last_quota_reset")
    now = datetime.now(timezone.utc)

    # Simple reset logic: if date is different, reset
    if not last_reset or last_reset.date() < now.date():
        current_user["quota_used"] = 0
        current_user["last_quota_reset"] = now
        if users_collection is not None:
            await users_collection.update_one(
                {"_id": current_user["_id"]},
                {"$set": {"quota_used": 0, "last_quota_reset": now}},
            )

    if current_user["quota_used"] >= current_user["quota_limit"]:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Daily usage quota exceeded. Please upgrade or try again tomorrow.",
        )

    # Increment quota
    if users_collection is not None:
        await users_collection.update_one(
            {"_id": current_user["_id"]}, {"$inc": {"quota_used": 1}}
        )
    current_user["quota_used"] += 1

    return current_user


async def require_admin(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return current_user


async def require_researcher(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in {"admin", "researcher"}:
        raise HTTPException(status_code=403, detail="Researcher privileges required")
    return current_user


async def require_viewer(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in {"admin", "researcher", "viewer"}:
        raise HTTPException(status_code=403, detail="Insufficient privileges")
    return current_user


# Backwards-compatible alias used by admin.py in the auth commit.
get_current_admin = require_admin
