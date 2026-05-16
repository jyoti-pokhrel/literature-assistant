import httpx
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.core.config import settings

logger = logging.getLogger(__name__)

async def send_email_via_smtp(to_email: str, subject: str, html_content: str):
    """Fallback to SMTP (Gmail) if Resend is unavailable or fails."""
    if not all([settings.EMAIL_HOST, settings.EMAIL_PORT, settings.EMAIL_USERNAME, settings.EMAIL_PASSWORD]):
        logger.warning("SMTP credentials missing. Skipping SMTP fallback.")
        return False

    try:
        msg = MIMEMultipart()
        msg["From"] = settings.EMAIL_USERNAME
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(html_content, "html"))

        # Using standard smtplib in a separate thread to avoid blocking the event loop
        # for a more robust async implementation, aiosmtplib could be used
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        def sync_send():
            with smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT) as server:
                server.starttls()
                server.login(settings.EMAIL_USERNAME, settings.EMAIL_PASSWORD)
                server.send_message(msg)

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(ThreadPoolExecutor(), sync_send)
        logger.info(f"Email sent via SMTP successfully to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email via SMTP: {str(e)}")
        return False

async def send_otp_email(email: str, otp: str):
    """Send an OTP email. Tries Resend first, then SMTP fallback."""
    subject = "Your Verification Code - Research Agent"
    html_content = f"""
    <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e4e4e7; border-radius: 12px;">
        <h2 style="color: #18181b;">Verify your email address</h2>
        <p style="color: #3f3f46; line-height: 1.5;">Welcome to Research Agent! Please use the following code to verify your account:</p>
        <div style="background: #f4f4f5; padding: 30px; text-align: center; border-radius: 10px; margin: 24px 0;">
            <h1 style="margin: 0; letter-spacing: 0.25em; font-size: 36px; color: #18181b; font-family: monospace;">{otp}</h1>
        </div>
        <p style="color: #71717a; font-size: 14px;">This code will expire in 5 minutes. If you didn't request this, you can ignore this email.</p>
    </div>
    """

    # 1. Try Resend if API key is set and it's not the default onboarding domain (or we want to try it anyway)
    if settings.RESEND_API_KEY:
        url = "https://api.resend.com/emails"
        headers = {
            "Authorization": f"Bearer {settings.RESEND_API_KEY}",
            "Content-Type": "application/json",
        }
        data = {
            "from": settings.EMAIL_FROM,
            "to": [email],
            "subject": subject,
            "html": html_content,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, headers=headers, json=data)
                if response.status_code < 400:
                    logger.info(f"OTP email sent successfully via Resend to {email}")
                    return
                else:
                    logger.warning(f"Resend failed (Status {response.status_code}): {response.text}. Falling back to SMTP.")
        except Exception as e:
            logger.warning(f"Resend error: {str(e)}. Falling back to SMTP.")

    # 2. Fallback to SMTP
    await send_email_via_smtp(email, subject, html_content)


async def send_reset_email(email: str, token: str):
    """Send a password reset email. Tries Resend first, then SMTP fallback."""
    subject = "Reset your password - Research Agent"
    # Use BACKEND_URL since FastAPI serves the frontend
    reset_link = f"{settings.BACKEND_URL}/html/reset-password.html?token={token}"
    
    html_content = f"""
    <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e4e4e7; border-radius: 12px;">
        <h2 style="color: #18181b;">Reset your password</h2>
        <p style="color: #3f3f46; line-height: 1.5;">We received a request to reset your password. Click the button below to choose a new one:</p>
        <div style="margin: 32px 0; text-align: center;">
            <a href="{reset_link}" style="background-color: #000; color: #fff; padding: 14px 28px; text-decoration: none; border-radius: 8px; font-weight: bold; display: inline-block;">Reset Password</a>
        </div>
        <p style="color: #71717a; font-size: 14px;">If you didn't request this, you can safely ignore this email. This link will expire in 15 minutes.</p>
        <hr style="border: none; border-top: 1px solid #e4e4e7; margin: 24px 0;" />
        <p style="color: #a1a1aa; font-size: 12px; word-break: break-all;">If the button doesn't work, copy and paste this URL into your browser:<br>{reset_link}</p>
    </div>
    """

    # 1. Try Resend
    if settings.RESEND_API_KEY:
        url = "https://api.resend.com/emails"
        headers = {
            "Authorization": f"Bearer {settings.RESEND_API_KEY}",
            "Content-Type": "application/json",
        }
        data = {
            "from": settings.EMAIL_FROM,
            "to": [email],
            "subject": subject,
            "html": html_content,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, headers=headers, json=data)
                if response.status_code < 400:
                    logger.info(f"Reset email sent successfully via Resend to {email}")
                    return
                else:
                    logger.warning(f"Resend failed (Status {response.status_code}): {response.text}. Falling back to SMTP.")
        except Exception as e:
            logger.warning(f"Resend error: {str(e)}. Falling back to SMTP.")

    # 2. Fallback to SMTP
    await send_email_via_smtp(email, subject, html_content)
