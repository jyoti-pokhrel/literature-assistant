from typing import Optional

from pydantic import BaseModel


class User(BaseModel):
    """MongoDB user document shape."""

    username: str
    email: str
    hashed_password: Optional[str] = None  # absent for Google OAuth users
    role: str = "student"
    is_verified: bool = False
    auth_provider: str = "local"  # "local" or "google"
