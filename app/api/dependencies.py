from fastapi import Depends, HTTPException, status, Header
from fastapi.security import OAuth2PasswordBearer
from app.core.security import decode_access_token
from app.db.session import get_db
from typing import Optional

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login", auto_error=False)

async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    x_api_key: Optional[str] = Header(None)
):
    """
    Dependency to get the current authenticated user from either JWT or API Key.
    """
    db = get_db()
    if db is None:
        raise HTTPException(status_code=500, detail="Database connection not initialized")

    user = None
    
    # 1. Try JWT
    if token:
        payload = decode_access_token(token)
        if payload:
            username = payload.get("sub")
            if username:
                user = await db.users.find_one({"username": username})

    # 2. Try API Key if JWT failed/missing
    if not user and x_api_key:
        user = await db.users.find_one({"api_key": x_api_key})

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    return user

async def require_admin(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return current_user

async def require_researcher(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["admin", "researcher"]:
        raise HTTPException(status_code=403, detail="Researcher privileges required")
    return current_user

async def require_viewer(current_user: dict = Depends(get_current_user)):
    # All authenticated users have at least viewer privileges
    return current_user

# For backwards compatibility with admin routes
get_current_admin = require_admin
