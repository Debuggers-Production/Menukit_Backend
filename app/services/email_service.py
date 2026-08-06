"""Email service for sending OTP codes."""

import logging
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class EmailService:
    """Pluggable email service. Console backend for development."""

    async def send_otp_email(self, email: str, otp_code: str) -> bool:
        """Send OTP code to the given email address."""
        if settings.EMAIL_BACKEND == "console":
            return await self._send_console(email, otp_code)
        elif settings.EMAIL_BACKEND == "smtp":
            return await self._send_smtp(email, otp_code)
        return False

    async def _send_console(self, email: str, otp_code: str) -> bool:
        """Log OTP to console (development mode)."""
        GREEN = "\033[92m"
        CYAN = "\033[96m"
        RESET = "\033[0m"
        BOLD = "\033[1m"
        
        logger.info(f"📧 OTP Email to {email}: {otp_code}")
        print(f"\n{CYAN}{'=' * 50}{RESET}")
        print(f"{CYAN}📧 OTP Email to: {BOLD}{email}{RESET}")
        print(f"{GREEN}🔑 OTP Code: {BOLD}{otp_code}{RESET}")
        print(f"{CYAN}⏰ Valid for {settings.OTP_EXPIRE_SECONDS // 60} minutes{RESET}")
        print(f"{CYAN}{'=' * 50}\n{RESET}")
        return True

    async def _send_smtp(self, email: str, otp_code: str) -> bool:
        """Send OTP via SMTP (production mode)."""
        try:
            import aiosmtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart

            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"Your SmartMenu QR Login Code: {otp_code}"
            msg["From"] = settings.SMTP_FROM_EMAIL
            msg["To"] = email

            html_content = f"""
            <html>
            <body style="font-family: 'Inter', sans-serif; padding: 40px; background: #f8fafc;">
                <div style="max-width: 400px; margin: 0 auto; background: white; border-radius: 16px; padding: 40px; box-shadow: 0 4px 24px rgba(0,0,0,0.08);">
                    <h1 style="color: #f97316; font-size: 24px; margin-bottom: 8px;">SmartMenu QR</h1>
                    <p style="color: #64748b; margin-bottom: 24px;">Your login verification code</p>
                    <div style="background: #fff7ed; border: 2px solid #f97316; border-radius: 12px; padding: 24px; text-align: center; margin-bottom: 24px;">
                        <span style="font-size: 36px; font-weight: 700; letter-spacing: 8px; color: #ea580c;">{otp_code}</span>
                    </div>
                    <p style="color: #94a3b8; font-size: 14px;">This code expires in {settings.OTP_EXPIRE_SECONDS // 60} minutes. Do not share it with anyone.</p>
                </div>
            </body>
            </html>
            """

            msg.attach(MIMEText(html_content, "html"))

            use_tls = settings.SMTP_PORT == 465
            start_tls = settings.SMTP_PORT == 587

            await aiosmtplib.send(
                msg,
                hostname=settings.SMTP_HOST,
                port=settings.SMTP_PORT,
                username=settings.SMTP_USER,
                password=settings.SMTP_PASSWORD,
                use_tls=use_tls,
                start_tls=start_tls,
            )
            return True
        except Exception as e:
            # ANSI escape codes for colored terminal output
            RED = "\033[91m"
            YELLOW = "\033[93m"
            RESET = "\033[0m"
            BOLD = "\033[1m"
            
            logger.error(f"{RED}{BOLD}❌ Failed to send email: {e}{RESET}")
            print(f"\n{RED}{'=' * 50}{RESET}")
            print(f"{RED}{BOLD}❌ EMAIL SEND ERROR: {e}{RESET}")
            print(f"{YELLOW}💡 Fallback Development OTP Code for {email}: {BOLD}{otp_code}{RESET}")
            print(f"{RED}{'=' * 50}\n{RESET}")
            return False
