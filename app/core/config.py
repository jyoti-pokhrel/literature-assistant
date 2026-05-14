import os
from pathlib import Path

from dotenv import load_dotenv

import logging as _logging

ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)


class Settings:
    MONGODB_URL = os.environ.get("MONGODB_URL", "mongodb://localhost:27017")
    DB_NAME = os.environ.get("DB_NAME", "research_agent")
    SECRET_KEY = os.environ.get("SECRET_KEY", "")
    ALGORITHM = os.environ.get("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES = int(
        os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "1440")
    )

    EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.gmail.com")
    EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
    EMAIL_USERNAME = os.environ.get("EMAIL_USERNAME", "")
    EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")

    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI = os.environ.get(
        "GOOGLE_REDIRECT_URI", "http://127.0.0.1:8000/auth/google/callback"
    )

    RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
    EMAIL_FROM = os.environ.get("EMAIL_FROM", "onboarding@resend.dev")

    FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://127.0.0.1:8000")
    BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")

    # Preserved from previous version (used by core API-key middleware, if any)
    API_KEY = os.environ.get("API_KEY", "")
    API_KEY_NAME = os.environ.get("API_KEY_NAME", "x-api-key")

    AUTH_DEV_BYPASS = os.environ.get("AUTH_DEV_BYPASS", "0") == "1"


settings = Settings()


if not settings.SECRET_KEY:
    _logging.getLogger(__name__).warning(
        "SECRET_KEY is not set; JWT operations will fail at runtime. "
        "Set SECRET_KEY in your .env before enabling auth."
    )
