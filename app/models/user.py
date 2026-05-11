# Database ma store hune user ko structure define garxa

from pydantic import BaseModel
from typing import Optional


class User(BaseModel):
    """
    MongoDB ma store hune user ko fields.
    Yo model database bata data read garda use hunxa.
    """
    username: str
    email: str
    hashed_password: Optional[str] = None  # Google user ko password hunchaina
    role: str = "student"                   # Default role student
    is_verified: bool = False               # OTP verify nagari False
    auth_provider: str = "local"            # "local" ya "google"