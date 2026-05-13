from pydantic import BaseModel, EmailStr, field_validator
from typing import Literal

class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    role: Literal["admin", "researcher", "student"]

    @field_validator("username")
    def username_valid(cls, v):
        v = v.strip()
        if len(v) < 3:
            raise ValueError("Username must be at least 3 characters")
        if len(v) > 20:
            raise ValueError("Username must not exceed 20 characters")
        if not v.isalnum():
            raise ValueError("Username must contain only letters and numbers")
        return v

    @field_validator("password")
    def password_valid(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not any(char.isdigit() for char in v):
            raise ValueError("Password must contain at least one number")
        if not any(char.isupper() for char in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(char.islower() for char in v):
            raise ValueError("Password must contain at least one lowercase letter")
        return v

class UserLogin(BaseModel):
    username: str
    password: str


from pydantic import Field
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