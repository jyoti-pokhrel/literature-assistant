from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Form, Request
from fastapi.security import OAuth2PasswordRequestForm
from typing import Optional
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
import httpx

from app.core.security import get_password_hash, verify_password, create_access_token
from app.core.config import settings
from app.db.session import get_db
from app.schemas.user import UserSignup, VerifyOTP, ResendOTP, ForgotPassword, ResetPassword
from app.utils.helpers import generate_otp, generate_reset_token, is_valid_password
from app.utils.email import send_otp_email, send_reset_email

"""
Authentication Module
---------------------
This module handles user registration, login, OTP verification, and password resets.

Key features:
1. JWT based authentication using OAuth2PasswordBearer.
2. Email verification via OTP (Resend API).
3. Google OAuth2 integration.
4. Role-based access control (RBAC) via dependencies.

To protect a route:
    from app.api.dependencies import get_current_user
    
    @router.get("/protected")
    async def my_route(user: dict = Depends(get_current_user)):
        ...

To restrict a route to admins:
    from app.api.dependencies import get_current_admin
    
    @router.get("/admin-only")
    async def admin_route(admin: dict = Depends(get_current_admin)):
        ...

Public endpoints are explicitly listed in main.py and do not require the dependency.
"""

router = APIRouter(tags=["auth"])

@router.post("/signup")
async def signup(user: UserSignup, background_tasks: BackgroundTasks):
    """
    Register a new user with local authentication.
    
    - Validates if username/email already exists.
    - Hashes the password using Argon2.
    - Sets default role to 'researcher'.
    - Generates and sends a verification OTP to the user's email.
    """
    db = get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database connection not available. Please check your MongoDB Atlas whitelist.")
    
    # Check if user exists
    existing_user = await db.users.find_one({"$or": [{"username": user.username}, {"email": user.email}]})
    if existing_user:
        raise HTTPException(status_code=409, detail="Username or email already registered")
        
    if not is_valid_password(user.password):
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters, contain 1 uppercase and 1 number")

    hashed_password = get_password_hash(user.password)
    
    user_doc = {
        "username": user.username,
        "email": user.email,
        "password": hashed_password,
        "is_verified": False,
        "auth_provider": "local",
        "role": "researcher",
        "created_at": datetime.now(timezone.utc)
    }
    
    await db.users.insert_one(user_doc)
    
    # Generate and save OTP
    otp = generate_otp()
    otp_doc = {
        "email": user.email,
        "otp": otp,
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5)
    }
    await db.otps.insert_one(otp_doc)
    
    background_tasks.add_task(send_otp_email, user.email, otp)
    
    return {"success": True, "message": "OTP sent to email. Please verify to complete signup.", "email": user.email}

@router.post("/verify-otp")
async def verify_otp(data: VerifyOTP):
    """
    Verify a user's email using the OTP sent during signup.
    
    - Validates OTP existence and expiration (5 minutes).
    - Marks the user as verified in the database.
    - Returns a JWT access token for immediate login.
    """
    db = get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database connection not available. Please check your MongoDB Atlas whitelist.")
    
    otp_doc = await db.otps.find_one({"email": data.email, "otp": data.otp})
    
    if not otp_doc:
        raise HTTPException(status_code=400, detail="Invalid OTP")
        
    expires_at = otp_doc["expires_at"]
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
        
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="OTP expired")
        
    # Mark user as verified
    await db.users.update_one({"email": data.email}, {"$set": {"is_verified": True}})
    
    # Delete used OTPs
    await db.otps.delete_many({"email": data.email})
    
    # Get user for token generation
    user = await db.users.find_one({"email": data.email})
    access_token = create_access_token(data={"sub": user["username"]})
    
    return {
        "success": True, 
        "message": "Email verified successfully.", 
        "access_token": access_token, 
        "username": user["username"]
    }

@router.post("/resend-otp")
async def resend_otp(data: ResendOTP, background_tasks: BackgroundTasks):
    """
    Resend a new verification OTP to the user's email.
    
    - Deletes any existing pending OTPs for the email.
    - Generates and sends a new 6-digit OTP.
    """
    db = get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database connection not available. Please check your MongoDB Atlas whitelist.")
    
    user = await db.users.find_one({"email": data.email})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    if user.get("is_verified"):
        raise HTTPException(status_code=400, detail="User already verified")
        
    # Delete old OTPs
    await db.otps.delete_many({"email": data.email})
    
    # Generate and save new OTP
    otp = generate_otp()
    otp_doc = {
        "email": data.email,
        "otp": otp,
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5)
    }
    await db.otps.insert_one(otp_doc)
    
    background_tasks.add_task(send_otp_email, data.email, otp)
    
    return {"success": True, "message": "New OTP sent"}

@router.post("/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    Authenticate a user and return a JWT access token.
    
    - Supports login via either Email or Username.
    - Verifies the hashed password.
    - Checks if the email has been verified.
    """
    db = get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database connection not available. Please check your MongoDB Atlas whitelist.")
    
    if "@" in form_data.username:
        user = await db.users.find_one({"email": form_data.username})
    else:
        user = await db.users.find_one({"username": form_data.username})

    if not user or user.get("auth_provider") != "local":
        raise HTTPException(status_code=400, detail="Incorrect email/username or password")
        
    if not verify_password(form_data.password, user["password"]):
        raise HTTPException(status_code=400, detail="Incorrect email/username or password")
        
    if not user.get("is_verified"):
        raise HTTPException(status_code=403, detail="Email not verified. Please verify your email.")
        
    access_token = create_access_token(data={"sub": user["username"]})
    
    return {"success": True, "access_token": access_token, "token_type": "bearer", "username": user["username"]}

@router.post("/forgot-password")
async def forgot_password(data: ForgotPassword, background_tasks: BackgroundTasks):
    """
    Initiate a password reset flow.
    
    - Generates a secure reset token valid for 15 minutes.
    - Sends a reset link to the user's email.
    - Returns success regardless of whether the email exists (security).
    """
    db = get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database connection not available. Please check your MongoDB Atlas whitelist.")
    
    user = await db.users.find_one({"email": data.email, "auth_provider": "local"})
    
    if user:
        token = generate_reset_token()
        token_doc = {
            "email": data.email,
            "token": token,
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=15)
        }
        # Update or insert
        await db.reset_tokens.update_one(
            {"email": data.email},
            {"$set": token_doc},
            upsert=True
        )
        
        background_tasks.add_task(send_reset_email, data.email, token)
        
    # Always return success for security
    return {"success": True, "message": "If an account with that email exists, a password reset link has been sent."}

@router.post("/reset-password")
async def reset_password(data: ResetPassword):
    """
    Reset a user's password using a valid reset token.
    
    - Validates token existence and expiration.
    - Updates the user's password in the database.
    - Automatically logs the user in by returning a JWT token.
    """
    db = get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="Database connection not available. Please check your MongoDB Atlas whitelist.")
    
    token_doc = await db.reset_tokens.find_one({"token": data.token})
    
    if not token_doc:
        raise HTTPException(status_code=400, detail="Invalid token")
        
    expires_at = token_doc["expires_at"]
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
        
    current_time = datetime.now(timezone.utc)
    
    if expires_at < current_time:
        raise HTTPException(status_code=410, detail="Token expired")
        
    if not is_valid_password(data.new_password):
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters, contain 1 uppercase and 1 number")
        
    hashed_password = get_password_hash(data.new_password)
    
    # Update user password
    await db.users.update_one({"email": token_doc["email"]}, {"$set": {"password": hashed_password}})
    
    # Delete token
    await db.reset_tokens.delete_one({"_id": token_doc["_id"]})
    
    # Get user for automatic login after password reset
    user = await db.users.find_one({"email": token_doc["email"]})
    access_token = create_access_token(data={"sub": user["username"]})
    
    return {
        "success": True, 
        "message": "Password reset successfully",
        "access_token": access_token,
        "username": user["username"]
    }

@router.get("/auth/google")
async def google_auth(request: Request):
    """
    Redirect the user to Google's OAuth2 authorization page.
    """
    from urllib.parse import urlencode
    
    # EXACT string from .env
    redirect_uri = settings.GOOGLE_REDIRECT_URI
    
    params = {
        "response_type": "code",
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent"
    }
    
    query_string = urlencode(params)
    url = f"https://accounts.google.com/o/oauth2/v2/auth?{query_string}"
    
    
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url)

@router.get("/auth/google/callback")
async def google_auth_callback(code: str):
    """
    Handle the OAuth2 callback from Google.
    
    - Exchanges the authorization code for tokens.
    - Retrieves user information (email, profile).
    - Creates a new user if they don't exist (default role: researcher).
    - Returns a redirect to the frontend with the JWT token.
    """
    # Exchange code for token
    token_url = "https://oauth2.googleapis.com/token"
    # Use exact string from .env
    redirect_uri = settings.GOOGLE_REDIRECT_URI
    data = {
        "code": code,
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(token_url, data=data)
        if response.status_code != 200:
            import logging
            body = response.text[:500]
            logging.getLogger(__name__).error(
                "Google token exchange failed: status=%s body=%s redirect_uri=%s client_id_set=%s client_secret_set=%s",
                response.status_code, body, redirect_uri,
                bool(settings.GOOGLE_CLIENT_ID), bool(settings.GOOGLE_CLIENT_SECRET),
            )
            try:
                err = response.json()
                msg = f"Google rejected token exchange: {err.get('error', 'unknown')} — {err.get('error_description', '')}"
            except Exception:
                msg = "Google authentication failed (token exchange)"
            raise HTTPException(status_code=400, detail=msg)

        access_token = response.json().get("access_token")

        # Get user info
        user_info_url = "https://www.googleapis.com/oauth2/v3/userinfo"
        headers = {"Authorization": f"Bearer {access_token}"}
        user_info_response = await client.get(user_info_url, headers=headers)

        if user_info_response.status_code != 200:
            import logging
            logging.getLogger(__name__).error(
                "Google userinfo failed: status=%s body=%s",
                user_info_response.status_code, user_info_response.text[:500],
            )
            raise HTTPException(status_code=400, detail="Could not retrieve user info from Google")
            
        user_info = user_info_response.json()
        email = user_info.get("email")
        
        if not email:
            raise HTTPException(status_code=400, detail="Email not provided by Google")
            
        db = get_db()
        if db is None:
            raise HTTPException(status_code=503, detail="Database connection not available. Please check your MongoDB Atlas whitelist.")
        user = await db.users.find_one({"email": email})
        
        if not user:
            # Create user
            username = email.split("@")[0]
            # Ensure unique username
            while await db.users.find_one({"username": username}):
                username = f"{username}_{generate_otp()[:3]}"
                
            user_doc = {
                "username": username,
                "email": email,
                "password": "", # No password for OAuth
                "is_verified": True,
                "auth_provider": "google",
                "role": "researcher",
                "created_at": datetime.now(timezone.utc)
            }
            await db.users.insert_one(user_doc)
            user = user_doc
            
        token = create_access_token(data={"sub": user["username"]})
        
        # Land on a dedicated callback page that just stores the token and
        # routes to /workspace (or ?next=). Avoids flashing the login form.
        FRONTEND_URL = settings.FRONTEND_URL
        encoded_username = quote(user['username'], safe='')
        final_redirect = f"{FRONTEND_URL}/html/oauth-callback.html#token={token}&username={encoded_username}"

        from fastapi.responses import RedirectResponse
        return RedirectResponse(final_redirect)
