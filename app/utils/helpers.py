from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
import secrets
import string
import re

def hashed_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed: str) -> bool:
    return pwd_context.verify(plain_password, hashed)


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
