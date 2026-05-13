from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime

class UserSignup(BaseModel):
    username: str = Field(
        ..., 
        min_length=3, 
        max_length=20, 
        pattern=r'^[a-zA-Z0-9_-]+$',
        description="Username must be 3-20 characters, alphanumeric with underscores/hyphens"
    )
    email: EmailStr = Field(..., description="A valid email address")
    password: str = Field(
        ..., 
        min_length=8, 
        max_length=100,
        description="Password must be at least 8 characters"
    )

class UserLogin(BaseModel):
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