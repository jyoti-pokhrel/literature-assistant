# Add Authentication (from commit 4f10f7c) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-apply the JWT + OTP + Google-OAuth authentication feature from the reverted commit `cdcaae8` / merge `4f10f7c`, cleanly grafted onto the current `main` branch without disturbing the citation-graph, library, projects, feedback, or synthesis features added since.

**Architecture:**
- Backend: pure-additive. New auth/admin/user/chat routers using JWT (python-jose) + Argon2 hashes + Resend-API email + Google OAuth. Existing `papers.py`, `reports.py`, `search.py`, `synthesis.py`, `citations.py`, `library.py`, `projects.py`, `feedback.py` are not touched (they already inject `get_current_user`).
- `app/db/session.py` keeps its current Motor pool / certifi / module-level-collection pattern. We only **add** indexes for new auth-side collections; we do not adopt the old `connect_to_mongo()` style.
- `app/api/dependencies.py` becomes a real JWT validator but keeps the existing "local-test-user" fallback when no `Authorization` header is supplied, so localhost workflows from CLAUDE.md keep working.
- Frontend: pure-additive. New auth HTML pages live in `frontend/html/`. `index.html` is untouched. `appStore.js` gets only an `isLoggedIn` getter and `logout()` method; the rest of the auth commit's appStore changes (which reverted unrelated cache logic) are discarded.

**Tech Stack:** FastAPI · Motor (async MongoDB) · python-jose (JWT) · passlib[argon2] · httpx (calls Resend API + Google OAuth) · Alpine.js · vanilla CSS.

**Source of truth for code:** Files are pulled from git commit `cdcaae8f876de13581d5baf23f46fe3523eb8054` using `git show cdcaae8:<path>`. **Do NOT cherry-pick the commit** (it contains unrelated synthesis/index.html rewrites).

**Out of scope (must NOT change):**
- `app/services/synthesis/*` (gap_generator, embeddings, report_pipeline, dataset_builder, etc.)
- `app/services/retrieval/*`
- `app/api/routes/synthesis.py`
- `app/schemas/synthesis.py`
- `frontend/html/index.html`
- `frontend/js/alpine/components/*`
- The `db_ctx.client = AsyncIOMotorClient(...)` style — keep the current `_make_client()` + `users_collection = db["users"]` module-level pattern.

---

## File Map

**New files (copy verbatim from cdcaae8 unless noted):**
- `app/api/routes/admin.py` — admin-only stats + user listing
- `app/api/routes/user.py` — per-user API-key management
- `app/api/routes/chat.py` — save/list chat history
- `app/utils/email.py` — Resend API helpers (`send_otp_email`, `send_reset_email`)
- `frontend/html/login.html`
- `frontend/html/signup.html`
- `frontend/html/verify-otp.html`
- `frontend/html/forgot-password.html`
- `frontend/html/reset-password.html`
- `frontend/html/admin.html`

**Modified files (selective merge):**
- `app/core/config.py` — replace with the cdcaae8 `Settings` class. Existing file only exports `API_KEY` / `API_KEY_NAME`; preserve those as attributes on `Settings`.
- `app/core/security.py` — replace with the cdcaae8 version (adds `verify_password`, `get_password_hash`, `decode_access_token`).
- `app/utils/helpers.py` — **append** `generate_otp`, `generate_reset_token`, `is_valid_password` to current file. Keep `hashed_password` and `verify_password` (they're already there and routes import them).
- `app/schemas/user.py` — **append** `UserSignup`, `UserLogin`, `APIKeyResponse`, `APIKeyInfo`, `VerifyOTP`, `ResendOTP`, `ForgotPassword`, `ResetPassword`, `ChatSave`, `PaperCache`. Keep `UserCreate` and the existing `UserLogin` validator (rename cdcaae8's `UserLogin` to `UserLoginRequest` to avoid clash).
- `app/models/user.py` — extend existing `User` model with `is_verified: bool = False` and `auth_provider: str = "local"`. Make `hashed_password: Optional[str] = None`.
- `app/db/session.py` — **append** index creation for `otps`, `reset_tokens`, `search_history`, `chat_history` inside `init_indexes()`. Also expose `get_db()` returning `db` for the new auth code that uses `db.users.find_one(...)` style. Do not change the `_make_client()` or `CLIENT_OPTIONS` block.
- `app/api/dependencies.py` — replace fake `get_current_user` with JWT-backed lookup against `users_collection`; add fallback to the legacy `{"username": "local-test-user", "role": "admin"}` when env var `AUTH_DEV_BYPASS=1` AND no token is supplied. Add `require_admin`, `require_researcher`, `require_viewer`, `get_current_admin` aliases.
- `app/api/routes/auth.py` — replace with the full cdcaae8 version, but adapt all `db = get_db(); db.users…` calls to use the helper added in `session.py`. No other adaptation needed because `get_db()` returns the same `db` object the old code expected.
- `app/main.py` — register `admin.router`, `user.router`, `chat.router`. Mount `/html` static directory (currently absent). Add `/admin-panel` route serving `admin.html`. Keep existing lifespan, middleware, and other routers untouched.
- `frontend/js/api.js` — change `localStorage.getItem("token")` / `setItem("token", …)` / `removeItem("token")` to `"access_token"` (3 occurrences) so the new auth pages and the existing api.js agree on a single key.
- `frontend/js/alpine/stores/appStore.js` — add only two things: an `isLoggedIn` getter and a `logout()` method on the `app` Alpine store. Discard the rest of the cdcaae8 diff (which reverts unrelated cache/sidebar behavior).
- `.env.example` — document `RESEND_API_KEY`, `EMAIL_FROM`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `FRONTEND_URL`, `BACKEND_URL`, `AUTH_DEV_BYPASS`.
- `pyproject.toml` — no change required; `python-jose[cryptography]`, `passlib[argon2]`, `httpx`, `pydantic[email]`, `python-multipart` are already pinned. (We use Resend via httpx, not the `resend` PyPI package.)

---

## Task 1: Add Settings class to `app/core/config.py`

**Files:**
- Modify: `app/core/config.py` (currently only exports `API_KEY` / `API_KEY_NAME`)

- [ ] **Step 1: Replace `app/core/config.py` contents**

Write exactly:

```python
import os
from pathlib import Path

from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)


class Settings:
    MONGODB_URL = os.environ.get("MONGODB_URL", "mongodb://localhost:27017")
    DB_NAME = os.environ.get("DB_NAME", "research_agent")
    SECRET_KEY = os.environ.get("SECRET_KEY", "secret")
    ALGORITHM = os.environ.get("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

    EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.gmail.com")
    EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
    EMAIL_USERNAME = os.environ.get("EMAIL_USERNAME", "")
    EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")

    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "http://127.0.0.1:8000/auth/google/callback")

    RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
    EMAIL_FROM = os.environ.get("EMAIL_FROM", "onboarding@resend.dev")

    FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://127.0.0.1:8000")
    BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")

    # Preserved from previous version (used by core API-key middleware, if any)
    API_KEY = os.environ.get("API_KEY", "")
    API_KEY_NAME = os.environ.get("API_KEY_NAME", "x-api-key")

    AUTH_DEV_BYPASS = os.environ.get("AUTH_DEV_BYPASS", "0") == "1"


settings = Settings()
```

- [ ] **Step 2: Verify nothing currently imports `API_KEY` directly**

Run: `rg -n "from app.core.config import (API_KEY|API_KEY_NAME)" app/`
Expected: no matches (verified at plan-write time). If matches appear, change them to `settings.API_KEY` / `settings.API_KEY_NAME`.

- [ ] **Step 3: Import smoke test**

Run: `python -c "from app.core.config import settings; print(settings.SECRET_KEY, settings.AUTH_DEV_BYPASS)"`
Expected: prints the SECRET_KEY value (or `secret` default) and `False`.

- [ ] **Step 4: Commit**

```bash
git add app/core/config.py
git commit -m "auth: replace core.config with Settings class"
```

---

## Task 2: Expand `app/core/security.py` with JWT helpers

**Files:**
- Modify: `app/core/security.py`

- [ ] **Step 1: Replace contents**

Write exactly:

```python
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str):
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None
```

- [ ] **Step 2: Confirm legacy callers still work**

Run: `rg -n "from app.core.security import" app/`
Expected: only `app/api/routes/auth.py` uses it (plus the new dependencies in Task 8). The existing legacy `auth.py` (about to be replaced in Task 9) imports `create_access_token` — that signature is preserved (it now accepts an optional `expires_delta`, but the positional `data` arg is unchanged).

- [ ] **Step 3: Commit**

```bash
git add app/core/security.py
git commit -m "auth: add JWT helpers and password hashing utilities"
```

---

## Task 3: Append OTP / reset / password-validation helpers to `app/utils/helpers.py`

**Files:**
- Modify: `app/utils/helpers.py`

- [ ] **Step 1: Append three functions and the required imports**

Open `app/utils/helpers.py`. The existing content (KEEP IT) is:

```python
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

def hashed_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed: str) -> bool:
    return pwd_context.verify(plain_password, hashed)
```

Add at the top (after the `pwd_context` line) the imports `import secrets`, `import string`, `import re`. Then append at the end of the file:

```python
def generate_otp(length: int = 6) -> str:
    return "".join(secrets.choice(string.digits) for _ in range(length))


def generate_reset_token() -> str:
    return secrets.token_urlsafe(32)


def is_valid_password(password: str) -> bool:
    if len(password) < 8:
        return False
    if not re.search(r"[A-Z]", password):
        return False
    if not re.search(r"\d", password):
        return False
    return True
```

- [ ] **Step 2: Verify**

Run: `python -c "from app.utils.helpers import generate_otp, generate_reset_token, is_valid_password; print(len(generate_otp()), len(generate_reset_token())>20, is_valid_password('Abcdef12'))"`
Expected output: `6 True True`

- [ ] **Step 3: Commit**

```bash
git add app/utils/helpers.py
git commit -m "auth: add OTP, reset-token, and password-validation helpers"
```

---

## Task 4: Add `app/utils/email.py`

**Files:**
- Create: `app/utils/email.py`

- [ ] **Step 1: Write the file**

Copy verbatim from `git show cdcaae8:app/utils/email.py`. The full content is:

```python
import httpx
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)


async def send_otp_email(email: str, otp: str):
    """Send an OTP email using Resend API via httpx."""
    if not settings.RESEND_API_KEY:
        logger.warning(f"No Resend API Key. Would have sent OTP {otp} to {email}")
        return

    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {settings.RESEND_API_KEY}",
        "Content-Type": "application/json",
    }
    data = {
        "from": settings.EMAIL_FROM,
        "to": [email],
        "subject": "Your Verification Code - Research Agent",
        "html": f"""
        <div style=\"font-family: sans-serif; max-width: 600px; margin: 0 auto;\">
            <h2>Verify your email address</h2>
            <p>Welcome to Research Agent! Please use the following code to verify your account:</p>
            <div style=\"background: #f4f4f5; padding: 20px; text-align: center; border-radius: 8px; margin: 24px 0;\">
                <h1 style=\"margin: 0; letter-spacing: 0.2em; font-size: 32px; color: #18181b;\">{otp}</h1>
            </div>
            <p style=\"color: #71717a; font-size: 14px;\">This code will expire in 5 minutes.</p>
        </div>
        """,
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=data)
            if response.status_code >= 400:
                logger.error(f"Failed to send OTP email via Resend: {response.text}")
            else:
                logger.info(f"OTP email sent successfully to {email}")
    except Exception as e:
        logger.error(f"Error sending OTP email: {str(e)}")


async def send_reset_email(email: str, token: str):
    """Send a password reset email using Resend API via httpx."""
    if not settings.RESEND_API_KEY:
        logger.warning(f"No Resend API Key. Would have sent reset token {token} to {email}")
        return

    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {settings.RESEND_API_KEY}",
        "Content-Type": "application/json",
    }
    reset_link = f"{settings.BACKEND_URL}/html/reset-password.html?token={token}"

    data = {
        "from": settings.EMAIL_FROM,
        "to": [email],
        "subject": "Reset your password - Research Agent",
        "html": f"""
        <div style=\"font-family: sans-serif; max-width: 600px; margin: 0 auto;\">
            <h2>Reset your password</h2>
            <p>We received a request to reset your password. Click the button below to choose a new one:</p>
            <div style=\"margin: 32px 0;\">
                <a href=\"{reset_link}\" style=\"background-color: #000; color: #fff; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold;\">Reset Password</a>
            </div>
            <p style=\"color: #71717a; font-size: 14px;\">If you didn't request this, you can safely ignore this email. This link will expire in 15 minutes.</p>
            <hr style=\"border: none; border-top: 1px solid #e4e4e7; margin: 24px 0;\" />
            <p style=\"color: #a1a1aa; font-size: 12px; word-break: break-all;\">If the button doesn't work, copy and paste this URL into your browser:<br>{reset_link}</p>
        </div>
        """,
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=data)
            if response.status_code >= 400:
                logger.error(f"Failed to send reset email via Resend: {response.text}")
            else:
                logger.info(f"Reset email sent successfully to {email}")
    except Exception as e:
        logger.error(f"Error sending reset email: {str(e)}")
```

If the easier path is to dump the original file rather than retype the HTML, run:
`git show cdcaae8:app/utils/email.py > app/utils/email.py`

- [ ] **Step 2: Smoke import**

Run: `python -c "from app.utils.email import send_otp_email, send_reset_email; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add app/utils/email.py
git commit -m "auth: add Resend email helpers for OTP and reset flows"
```

---

## Task 5: Extend `app/schemas/user.py` with auth schemas

**Files:**
- Modify: `app/schemas/user.py`

- [ ] **Step 1: Append new schemas (keep existing `UserCreate` + `UserLogin`)**

At the bottom of `app/schemas/user.py`, append:

```python
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
```

- [ ] **Step 2: Verify imports**

Run: `python -c "from app.schemas.user import UserSignup, VerifyOTP, ResendOTP, ForgotPassword, ResetPassword, APIKeyResponse, APIKeyInfo, ChatSave; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add app/schemas/user.py
git commit -m "auth: add UserSignup, OTP, reset, and API-key schemas"
```

---

## Task 6: Extend `app/models/user.py`

**Files:**
- Modify: `app/models/user.py`

- [ ] **Step 1: Replace contents**

Write exactly:

```python
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
```

- [ ] **Step 2: Verify nothing depends on the old narrower shape**

Run: `rg -n "from app.models.user import" app/`
Expected: any matches still type-check since we only widened the model (added optional fields, made `hashed_password` optional). Skim each match to confirm.

- [ ] **Step 3: Commit**

```bash
git add app/models/user.py
git commit -m "auth: extend User model with verification + auth_provider"
```

---

## Task 7: Add indexes + `get_db()` helper to `app/db/session.py`

**Files:**
- Modify: `app/db/session.py`

- [ ] **Step 1: Add new collection module-level references**

Find the existing collection-references block (currently ends with `feedback_collection = db["feedback"] if db is not None else None`). Add directly after it:

```python
otps_collection = db["otps"] if db is not None else None
reset_tokens_collection = db["reset_tokens"] if db is not None else None
search_history_collection = db["search_history"] if db is not None else None
chat_history_collection = db["chat_history"] if db is not None else None
```

- [ ] **Step 2: Add a `get_db()` helper near the bottom of the file**

After the existing `close_db()` function, append:

```python
def get_db():
    """Return the active Motor database handle (or None if Mongo is not configured)."""
    return db
```

This lets auth.py / admin.py / user.py / chat.py keep their `db = get_db(); db.users.find_one(...)` style without forcing them to import a specific collection.

- [ ] **Step 3: Extend `init_indexes()` to bootstrap auth-side indexes**

Inside `init_indexes()`, after the existing `gap_reports_collection` index, append:

```python
    # users — role index used by admin panel filters
    await _safe_create_index(users_collection, "role")

    # OTPs: TTL via expires_at (the document sets expires_at = now + 5min)
    await _safe_create_index(otps_collection, "expires_at", expireAfterSeconds=0)
    await _safe_create_index(otps_collection, "email")

    # Reset tokens: TTL + lookup by token
    await _safe_create_index(reset_tokens_collection, "expires_at", expireAfterSeconds=0)
    await _safe_create_index(reset_tokens_collection, "email")
    await _safe_create_index(reset_tokens_collection, "token", unique=True)

    # Search / chat history
    await _safe_create_index(search_history_collection, "username")
    await _safe_create_index(search_history_collection, "created_at")
    await _safe_create_index(chat_history_collection, "username")
    await _safe_create_index(chat_history_collection, "created_at")
```

- [ ] **Step 4: Verify import surface**

Run: `python -c "from app.db.session import users_collection, otps_collection, reset_tokens_collection, get_db; print('ok')"`
Expected: `ok` (otps_collection / reset_tokens_collection / get_db may be `None` if `.env` lacks `MONGODB_URL`, that's fine).

- [ ] **Step 5: Commit**

```bash
git add app/db/session.py
git commit -m "auth: add otps/reset_tokens/history collections and get_db helper"
```

---

## Task 8: Replace `app/api/dependencies.py` with real auth + dev bypass

**Files:**
- Modify: `app/api/dependencies.py`

- [ ] **Step 1: Replace contents**

Write exactly:

```python
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
            return {"username": "local-test-user", "role": "admin", "is_verified": True}
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
    if current_user.get("role") not in {"admin", "researcher"}:
        raise HTTPException(status_code=403, detail="Researcher privileges required")
    return current_user


async def require_viewer(current_user: dict = Depends(get_current_user)):
    return current_user


# Backwards-compatible alias used by admin.py in the auth commit.
get_current_admin = require_admin
```

- [ ] **Step 2: Smoke import**

Run: `python -c "from app.api.dependencies import get_current_user, require_admin, require_researcher, require_viewer, get_current_admin; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Manual verification of dev bypass**

Start backend (`python -m uvicorn app.main:app --port 8000`). With `.env` containing `AUTH_DEV_BYPASS=1`, hit `curl http://localhost:8000/papers` — should succeed (mode = local-test-user). Set `AUTH_DEV_BYPASS=0`, hit it again — expect `401`. (Backend restart required between toggles.)

- [ ] **Step 4: Commit**

```bash
git add app/api/dependencies.py
git commit -m "auth: implement JWT-backed get_current_user with dev bypass"
```

---

## Task 9: Replace `app/api/routes/auth.py` with full flow

**Files:**
- Modify: `app/api/routes/auth.py`

- [ ] **Step 1: Dump the source from cdcaae8 as a starting point**

Run: `git show cdcaae8:app/api/routes/auth.py > app/api/routes/auth.py`

- [ ] **Step 2: Verify the file now contains the full flow**

Run: `rg -n "^@router\." app/api/routes/auth.py`
Expected lines (paths): `/signup`, `/verify-otp`, `/resend-otp`, `/login`, `/forgot-password`, `/reset-password`, `/auth/google`, `/auth/google/callback`.

The file imports `from app.db.session import get_db` which now exists (Task 7) and returns the same `db` handle the function bodies expect (`db.users.find_one`, `db.otps.insert_one`, `db.reset_tokens.update_one`, etc.).

- [ ] **Step 3: Remove debug `print()` statements**

Open `app/api/routes/auth.py`, delete every line that begins with `print(f"DEBUG:` (there are five in reset_password and two in the Google callback). Keep `logger.info` / `logger.error` if any.

- [ ] **Step 4: Smoke import**

Run: `python -c "from app.api.routes.auth import router; print(len(router.routes))"`
Expected: a positive integer (around 8).

- [ ] **Step 5: Commit**

```bash
git add app/api/routes/auth.py
git commit -m "auth: replace auth route with full signup/login/OTP/reset/Google flow"
```

---

## Task 10: Add `app/api/routes/admin.py`

**Files:**
- Create: `app/api/routes/admin.py`

- [ ] **Step 1: Dump the file**

Run: `git show cdcaae8:app/api/routes/admin.py > app/api/routes/admin.py`

- [ ] **Step 2: Verify imports resolve**

Run: `python -c "from app.api.routes.admin import router; print('ok')"`
Expected: `ok`. The router uses `get_current_admin` (now provided by `app/api/dependencies.py`) and `get_db()` (provided by Task 7).

- [ ] **Step 3: Commit**

```bash
git add app/api/routes/admin.py
git commit -m "auth: add admin router (stats + user listing)"
```

---

## Task 11: Add `app/api/routes/user.py`

**Files:**
- Create: `app/api/routes/user.py`

- [ ] **Step 1: Dump the file**

Run: `git show cdcaae8:app/api/routes/user.py > app/api/routes/user.py`

- [ ] **Step 2: Verify**

Run: `python -c "from app.api.routes.user import router; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add app/api/routes/user.py
git commit -m "auth: add per-user API-key management router"
```

---

## Task 12: Add `app/api/routes/chat.py`

**Files:**
- Create: `app/api/routes/chat.py`

- [ ] **Step 1: Dump the file**

Run: `git show cdcaae8:app/api/routes/chat.py > app/api/routes/chat.py`

- [ ] **Step 2: Verify**

Run: `python -c "from app.api.routes.chat import router; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add app/api/routes/chat.py
git commit -m "auth: add chat-history router"
```

---

## Task 13: Wire new routers + `/html` mount into `app/main.py`

**Files:**
- Modify: `app/main.py`

- [ ] **Step 1: Update the routes import line**

Find this line in `app/main.py`:

```python
from app.api.routes import auth, citations, papers, reports, search, synthesis
```

Replace with:

```python
from app.api.routes import auth, admin, chat, citations, papers, reports, search, synthesis, user
```

(Note: `projects`, `library`, `feedback` are imported lazily elsewhere — only modules currently imported on this line need to be present here.)

- [ ] **Step 2: Register the new routers**

After the existing `app.include_router(citations.router)` line, add:

```python
app.include_router(admin.router)
app.include_router(user.router)
app.include_router(chat.router)
```

- [ ] **Step 3: Mount `/html` and add `/admin-panel` route**

After the existing block:

```python
app.mount("/css", StaticFiles(directory=FRONTEND_DIR / "css"), name="frontend-css")
app.mount("/js", StaticFiles(directory=FRONTEND_DIR / "js"), name="frontend-js")
```

Add:

```python
app.mount("/html", StaticFiles(directory=FRONTEND_DIR / "html"), name="frontend-html")
```

And below the existing `frontend_share_link` route, add:

```python
ADMIN_PAGE = FRONTEND_DIR / "html" / "admin.html"


@app.get("/admin-panel", include_in_schema=False)
def frontend_admin_panel():
    return FileResponse(ADMIN_PAGE)
```

- [ ] **Step 4: Smoke import**

Run: `python -c "from app.main import app; print(len(app.routes))"`
Expected: a positive integer larger than before. No ImportError.

- [ ] **Step 5: Start server and check OpenAPI for new endpoints**

Start: `python -m uvicorn app.main:app --port 8000` (in another terminal or background).
Run: `curl -s http://localhost:8000/openapi.json | python -c "import json, sys; d=json.load(sys.stdin); print(sorted(p for p in d['paths'] if any(s in p for s in ['/admin','/user/api-key','/chat','/signup','/login','/forgot','/reset','/verify-otp'])))"`
Expected: should include `/admin/users`, `/admin/stats`, `/user/api-key`, `/chat/save`, `/chat/history`, `/signup`, `/login`, `/forgot-password`, `/reset-password`, `/verify-otp`.

Stop the server.

- [ ] **Step 6: Commit**

```bash
git add app/main.py
git commit -m "auth: register admin/user/chat routers and mount /html assets"
```

---

## Task 14: Add `frontend/html/login.html`

**Files:**
- Create: `frontend/html/login.html`

- [ ] **Step 1: Dump the file**

Run: `git show cdcaae8:frontend/html/login.html > frontend/html/login.html`

- [ ] **Step 2: Verify visually**

Start the dev server, open `http://localhost:8000/html/login.html`. Confirm: form renders, "Continue with Google" button present, dark-mode toggle works.

- [ ] **Step 3: Commit**

```bash
git add frontend/html/login.html
git commit -m "auth: add login page"
```

---

## Task 15: Add `frontend/html/signup.html`

**Files:**
- Create: `frontend/html/signup.html`

- [ ] **Step 1:** `git show cdcaae8:frontend/html/signup.html > frontend/html/signup.html`
- [ ] **Step 2:** Open `http://localhost:8000/html/signup.html`. Confirm form renders.
- [ ] **Step 3:**

```bash
git add frontend/html/signup.html
git commit -m "auth: add signup page"
```

---

## Task 16: Add `frontend/html/verify-otp.html`

**Files:**
- Create: `frontend/html/verify-otp.html`

- [ ] **Step 1:** `git show cdcaae8:frontend/html/verify-otp.html > frontend/html/verify-otp.html`
- [ ] **Step 2:** Open `http://localhost:8000/html/verify-otp.html?email=test@example.com`. Confirm OTP input renders.
- [ ] **Step 3:**

```bash
git add frontend/html/verify-otp.html
git commit -m "auth: add OTP verification page"
```

---

## Task 17: Add `frontend/html/forgot-password.html`

**Files:**
- Create: `frontend/html/forgot-password.html`

- [ ] **Step 1:** `git show cdcaae8:frontend/html/forgot-password.html > frontend/html/forgot-password.html`
- [ ] **Step 2:** Open `http://localhost:8000/html/forgot-password.html`. Confirm form renders.
- [ ] **Step 3:**

```bash
git add frontend/html/forgot-password.html
git commit -m "auth: add forgot-password page"
```

---

## Task 18: Add `frontend/html/reset-password.html`

**Files:**
- Create: `frontend/html/reset-password.html`

- [ ] **Step 1:** `git show cdcaae8:frontend/html/reset-password.html > frontend/html/reset-password.html`
- [ ] **Step 2:** Open `http://localhost:8000/html/reset-password.html?token=fake`. Confirm form renders (token will be invalid; that's expected at this stage).
- [ ] **Step 3:**

```bash
git add frontend/html/reset-password.html
git commit -m "auth: add reset-password page"
```

---

## Task 19: Add `frontend/html/admin.html`

**Files:**
- Create: `frontend/html/admin.html`

- [ ] **Step 1:** `git show cdcaae8:frontend/html/admin.html > frontend/html/admin.html`
- [ ] **Step 2:** Open `http://localhost:8000/admin-panel`. Confirm page renders. (User listing will be empty / 401 until login is wired.)
- [ ] **Step 3:**

```bash
git add frontend/html/admin.html
git commit -m "auth: add admin panel page"
```

---

## Task 20: Align localStorage token key in `frontend/js/api.js`

**Files:**
- Modify: `frontend/js/api.js`

- [ ] **Step 1: Replace the three localStorage keys**

In `frontend/js/api.js`, change each occurrence of the string `"token"` used with `localStorage` to `"access_token"`. There are exactly three: a `getItem`, a `setItem` (inside `login`), and a `removeItem` (inside `logout`).

For exactness:

```javascript
const token = localStorage.getItem("token");
```
becomes
```javascript
const token = localStorage.getItem("access_token");
```

```javascript
localStorage.setItem("token", data.access_token)
```
becomes
```javascript
localStorage.setItem("access_token", data.access_token)
```

```javascript
localStorage.removeItem("token")
```
becomes
```javascript
localStorage.removeItem("access_token")
```

- [ ] **Step 2: Verify**

Run: `rg -n 'localStorage.*"token"' frontend/js/api.js`
Expected: no matches.

Run: `rg -n 'localStorage.*"access_token"' frontend/js/api.js`
Expected: 3 matches.

- [ ] **Step 3: Commit**

```bash
git add frontend/js/api.js
git commit -m "auth: align api.js token storage key with auth pages"
```

---

## Task 21: Add `isLoggedIn` getter + `logout()` to `appStore.js`

**Files:**
- Modify: `frontend/js/alpine/stores/appStore.js`

- [ ] **Step 1: Locate the `Alpine.store('app', { ... })` block**

Find the line `Alpine.store('app', {` and the property `initialized: false,` directly below it. Immediately after `initialized: false,` add:

```javascript
        get isLoggedIn() {
            const token = localStorage.getItem('access_token');
            return !!(token && token !== 'undefined' && token !== 'null');
        },
```

- [ ] **Step 2: Add a `logout()` method**

Locate the existing `goLanding()` method (around line 460 in the current file). Add directly after its closing brace:

```javascript
        logout() {
            localStorage.removeItem('access_token');
            localStorage.removeItem('username');
            window.location.href = window.ResearchAgent.routes.landing;
        },
```

**DO NOT** modify any other part of `appStore.js`. The auth commit's diff also reverts `sidebarStateKey` from `v2` to `v1`, removes server-side cache logic in `useHistoryItem`, and drops the `regenerate` param — all of those are unrelated to authentication and **must be left alone**.

- [ ] **Step 3: Verify only two additions**

Run: `git diff frontend/js/alpine/stores/appStore.js | rg "^[+-]" | rg -v "^(---|\+\+\+)"` and confirm only the additions described above appear. No `-` (removal) lines.

- [ ] **Step 4: Browser sanity check**

Open `http://localhost:8000/workspace`, in the DevTools console run `Alpine.store('app').isLoggedIn` — should return `false` (no token in localStorage). Run `Alpine.store('app').logout()` — should redirect to `/`.

- [ ] **Step 5: Commit**

```bash
git add frontend/js/alpine/stores/appStore.js
git commit -m "auth: expose isLoggedIn + logout on Alpine app store"
```

---

## Task 22: Document new env vars in `.env.example`

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Append a new section**

At the end of `.env.example`, append:

```
# === Authentication ===
# Set to "1" to bypass auth and return a synthetic admin user when no
# Authorization header is sent. Useful for localhost. Set to "0" in any
# environment where you want real auth enforcement.
AUTH_DEV_BYPASS=1

# Resend API (used for OTP + password reset emails). If empty, emails are logged instead of sent.
RESEND_API_KEY=
EMAIL_FROM=onboarding@resend.dev

# Google OAuth
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/auth/google/callback

# URLs used by email links and the OAuth redirect target
FRONTEND_URL=http://127.0.0.1:8000
BACKEND_URL=http://127.0.0.1:8000
```

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "auth: document new env vars for JWT, Resend, Google OAuth"
```

---

## Task 23: End-to-end smoke test

**Files:** none modified — verification only.

- [ ] **Step 1: Update local `.env`**

Ensure `.env` contains `SECRET_KEY=<any random string>`, `ALGORITHM=HS256`, `ACCESS_TOKEN_EXPIRE_MINUTES=1440`, `AUTH_DEV_BYPASS=1` (for now). Leave `RESEND_API_KEY` empty — the OTP will be logged to the console.

- [ ] **Step 2: Start the backend**

Run: `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`

- [ ] **Step 3: Confirm pre-existing features still work (regression check)**

In a second terminal:

```bash
curl -s -X POST http://localhost:8000/search/papers \
  -H 'Content-Type: application/json' \
  -d '{"topic": "graph neural networks", "max_results": 3}' | head -c 400
```

Expected: a JSON response with papers (because `AUTH_DEV_BYPASS=1`). If you get `401`, the dev bypass isn't loading — check `.env` and that `app/api/dependencies.py` references `settings.AUTH_DEV_BYPASS`.

Also load `http://localhost:8000/workspace` in a browser — search form should render, no JS errors.

- [ ] **Step 4: Signup → OTP → login happy path**

```bash
curl -s -X POST http://localhost:8000/signup \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","email":"alice@example.com","password":"Abcdef12"}'
```

Watch the server log for `Would have sent OTP NNNNNN to alice@example.com`. Copy the 6-digit code, then:

```bash
curl -s -X POST http://localhost:8000/verify-otp \
  -H 'Content-Type: application/json' \
  -d '{"email":"alice@example.com","otp":"<NNNNNN>"}'
```

Expect `{"success": true, …, "access_token": "<JWT>", "username":"alice"}`.

- [ ] **Step 5: Authenticated request with the new token**

```bash
curl -s http://localhost:8000/papers -H "Authorization: Bearer <JWT>"
```

Expect a 200. With a deliberately wrong token, expect 401.

- [ ] **Step 6: Verify auth bypass disabling works**

Stop server. Set `AUTH_DEV_BYPASS=0`. Restart. Hit `/papers` without a token — expect 401. Hit it with the JWT from Step 4 — expect 200.

- [ ] **Step 7: Browser smoke**

Visit `/html/login.html`, log in as `alice` / `Abcdef12`. After login, DevTools should show `localStorage.access_token` set. Navigate to `/workspace` and run a search — should still work.

- [ ] **Step 8: Commit a note if any fix-ups were needed**

If everything passes without code changes, no commit needed. If a fix was required, commit it with a message like `auth: fix <description>`.

---

## Self-Review Notes (recorded at plan-write time)

- **Spec coverage:** Signup, OTP, resend-OTP, login, forgot-password, reset-password, Google OAuth, admin user-list/stats, per-user API keys, chat history — each maps to Task 9–12. Frontend pages — Task 14–19. Token storage alignment — Task 20. Logged-in state on Alpine store — Task 21. Env documentation — Task 22.
- **No-break guarantee:**
  - The synthesis pipeline (`gap_generator.py`, `embeddings.py`, `report_pipeline.py`) is never touched.
  - `app/db/session.py` keeps its current `_make_client()` pool tuning; we only append.
  - The frontend `index.html` is left alone — the auth commit's reverted version is **never** reintroduced.
  - The legacy `get_current_user → {"username": "local-test-user", "role": "admin"}` behavior is preserved as a dev bypass triggered by `AUTH_DEV_BYPASS=1`.
- **Type / signature consistency:** `get_current_user` returns a dict (real Mongo doc OR the synthetic dict) — matches what every existing route already assumes (`current_user["username"]`). `require_admin`/`require_researcher`/`require_viewer` all return the same dict. `create_access_token(data, expires_delta=None)` adds an optional kwarg — existing callers stay compatible.
- **Placeholders:** none — every step contains the exact file content, exact `git show` command, or exact verification command.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-13-add-authentication.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
