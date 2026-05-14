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
        <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
            <h2>Verify your email address</h2>
            <p>Welcome to Research Agent! Please use the following code to verify your account:</p>
            <div style="background: #f4f4f5; padding: 20px; text-align: center; border-radius: 8px; margin: 24px 0;">
                <h1 style="margin: 0; letter-spacing: 0.2em; font-size: 32px; color: #18181b;">{otp}</h1>
            </div>
            <p style="color: #71717a; font-size: 14px;">This code will expire in 5 minutes.</p>
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
        logger.warning(
            f"No Resend API Key. Would have sent reset token {token} to {email}"
        )
        return

    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {settings.RESEND_API_KEY}",
        "Content-Type": "application/json",
    }

    # Use BACKEND_URL since FastAPI serves the frontend
    reset_link = f"{settings.BACKEND_URL}/html/reset-password.html?token={token}"

    data = {
        "from": settings.EMAIL_FROM,
        "to": [email],
        "subject": "Reset your password - Research Agent",
        "html": f"""
        <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
            <h2>Reset your password</h2>
            <p>We received a request to reset your password. Click the button below to choose a new one:</p>
            <div style="margin: 32px 0;">
                <a href="{reset_link}" style="background-color: #000; color: #fff; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold;">Reset Password</a>
            </div>
            <p style="color: #71717a; font-size: 14px;">If you didn't request this, you can safely ignore this email. This link will expire in 15 minutes.</p>
            <hr style="border: none; border-top: 1px solid #e4e4e7; margin: 24px 0;" />
            <p style="color: #a1a1aa; font-size: 12px; word-break: break-all;">If the button doesn't work, copy and paste this URL into your browser:<br>{reset_link}</p>
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
