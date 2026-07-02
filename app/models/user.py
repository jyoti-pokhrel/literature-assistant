from datetime import datetime
from typing import Optional, Literal

from pydantic import BaseModel


class User(BaseModel):
    """MongoDB user document shape."""

    username: str
    email: str
    hashed_password: Optional[str] = None  # absent for Google OAuth users
    role: Literal["system_user", "admin", "researcher", "viewer"] = "researcher"
    is_verified: bool = False
    auth_provider: str = "local"  # "local" or "google"
    
    # API Key management
    api_key: Optional[str] = None
    api_key_created_at: Optional[datetime] = None
    
    # Usage quotas
    quota_limit: int = 100  # daily request limit
    quota_used: int = 0
    last_quota_reset: Optional[datetime] = None
    created_at: Optional[datetime] = None
