from typing import Optional
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime


class UserSignup(BaseModel):
    username: str = Field(
        ...,
        min_length=3,
        max_length=20,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Username must be 3-20 characters, alphanumeric with underscores/hyphens",
    )
    email: EmailStr = Field(..., description="A valid email address")
    password: str = Field(..., min_length=8, max_length=100)


class UserLoginRequest(BaseModel):
    """Used for JSON-body login if needed; the actual /login uses OAuth2 form."""

    username: str = Field(..., description="Email or Username")
    password: str


class APIKeyResponse(BaseModel):
    api_key: str
    message: str = "Keep this key safe. It will not be shown again."


class APIKeyInfo(BaseModel):
    api_key_masked: str
    created_at: datetime


class VerifyOTP(BaseModel):
    email: EmailStr
    otp: str


class ResendOTP(BaseModel):
    email: EmailStr


class ForgotPassword(BaseModel):
    email: EmailStr


class ResetPassword(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8)


class UserQuota(BaseModel):
    quota_limit: int
    quota_used: int
    remaining: int
    last_reset: Optional[datetime]


class UpdateUsername(BaseModel):
    new_username: str = Field(
        ...,
        min_length=3,
        max_length=20,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="New username: 3-20 chars, alphanumeric with underscores/hyphens",
    )


class UpdatePassword(BaseModel):
    current_password: str = Field(..., min_length=1, description="Current password for verification")
    new_password: str = Field(..., min_length=8, max_length=100, description="New password")


class UserUpdate(BaseModel):
    role: Optional[str] = None
    quota_limit: Optional[int] = None
    is_verified: Optional[bool] = None
    is_active: Optional[bool] = None


class UserProfile(BaseModel):
    username: str
    email: str
    role: str
    is_verified: bool
    auth_provider: str
    created_at: Optional[datetime]
    quota: Optional[UserQuota] = None


class ChatSave(BaseModel):
    query: str
    results: list
    source: str


class PaperCache(BaseModel):
    paper_id: str
    title: str
    authors: list
    abstract: str
    year: int
    source: str
