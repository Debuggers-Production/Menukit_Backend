from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.session import get_db
from app.database.redis import get_redis
from app.core.deps import get_current_user
from app.core.exceptions import BadRequestException, RateLimitException
from app.schemas.auth import (
    OTPRequest, OTPVerify, TokenResponse, RefreshTokenRequest, UserResponse,
    ChangeEmailRequest, PhoneOTPRequest, PhoneOTPVerify
)
from sqlalchemy import select
from app.schemas.common import MessageResponse
from app.services.otp_service import OTPService
from app.services.email_service import EmailService
from app.services.auth_service import AuthService
from app.models.user import User
from icecream import ic
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/request-otp", response_model=MessageResponse)
async def request_otp(
    data: OTPRequest,
    redis=Depends(get_redis),
):
    """Send OTP to the provided email address."""
    otp_service = OTPService(redis)
    code = await otp_service.create_otp(data.email)
    ic("OTP CODE :",code)

    if code is None:
        raise RateLimitException("Too many OTP requests. Please try again later.")

    from app.core.config import get_settings
    settings = get_settings()
    clean_email = data.email.strip().lower()
    if getattr(settings, "ALLOW_TEST_EMAIL", False) and clean_email == getattr(settings, "TEST_EMAIL", "").strip().lower():
        print(f"🔑 [TEST EMAIL OTP BYPASS] Using test OTP '{settings.TEST_EMAIL_OTP}' for test email '{clean_email}'")
        return MessageResponse(message="OTP sent successfully to your email")

    email_service = EmailService()
    sent = await email_service.send_otp_email(data.email, code)

    if not sent:
        raise BadRequestException("Failed to send OTP email. Please check email/SMTP configuration.")

    return MessageResponse(message="OTP sent successfully to your email")


@router.post("/verify-otp", response_model=TokenResponse)
async def verify_otp(
    data: OTPVerify,
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """Verify OTP and return JWT tokens."""
    otp_service = OTPService(redis)
    is_valid = await otp_service.verify_otp(data.email, data.code)

    if not is_valid:
        raise BadRequestException("Invalid or expired OTP code")

    auth_service = AuthService(db)
    user = await auth_service.get_or_create_user(data.email)

    # Extract request info
    user_agent = request.headers.get("user-agent", "")
    ip_address = request.client.host if request.client else None

    tokens = await auth_service.create_session(
        user=user,
        device_info=user_agent[:200] if user_agent else None,
        browser_info=user_agent[:200] if user_agent else None,
        ip_address=ip_address,
    )

    await db.commit()
    return TokenResponse(**tokens)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    data: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    """Refresh access token using refresh token."""
    auth_service = AuthService(db)
    result = await auth_service.refresh_session(data.refresh_token)
    if not result:
        raise BadRequestException("Invalid or expired refresh token")

    return TokenResponse(**result)


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Logout and invalidate sessions."""
    auth_service = AuthService(db)
    ip_address = request.client.host if request.client else None
    await auth_service.logout(user.id, ip_address)

    return MessageResponse(message="Logged out successfully")


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)):
    """Get current user profile."""
    return UserResponse(
        id=str(user.id),
        email=user.email,
        phone=user.phone,
        phone_verified=bool(user.phone_verified),
        role=user.role,
        is_active=user.is_active,
        last_login=str(user.last_login) if user.last_login else None,
        created_at=str(user.created_at),
    )


@router.post("/phone/send-otp", response_model=MessageResponse)
async def send_phone_otp(
    data: PhoneOTPRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """Send SMS OTP to verify user's authentication mobile number."""
    clean_digits = "".join(c for c in str(data.phone) if c.isdigit())
    if len(clean_digits) < 10:
        raise BadRequestException("Please provide a valid 10-digit mobile number")
    
    country_code = data.country_code.strip() if data.country_code else "+91"
    if not country_code.startswith("+"):
        country_code = f"+{country_code}"
    
    ten_digit = clean_digits[-10:]
    formatted_phone = f"{country_code}{ten_digit}"
    
    # Check if this phone number is already verified by another user
    from app.core.config import is_phone_exempt
    if not is_phone_exempt(formatted_phone):
        stmt = select(User).where(User.phone == formatted_phone, User.phone_verified == True, User.id != user.id)
        res = await db.execute(stmt)
        existing_user = res.scalar_one_or_none()
        if existing_user:
            raise BadRequestException("This mobile number is already verified with another account.")

    # 1. Rate Limit & Fallback OTP creation (Max 3 attempts)
    otp_service = OTPService(redis)
    phone_key = f"phone:{user.id}:{formatted_phone}"
    code = await otp_service.create_otp(phone_key, rate_limit_type="phone_auth")
    if code is None:
        raise RateLimitException("You have reached the maximum 3 OTP attempts. Please wait 15 minutes before trying again.")

    # 2. Send via SMSService (MSG91 Widget)
    from app.services.sms_service import sms_service
    verification_id = await sms_service.send_otp(mobile_number=formatted_phone, country_code=country_code.replace("+", ""))
    
    if not verification_id and not sms_service.mock_mode:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send OTP via SMS. Please try again later."
        )

    # Store verification ID in Redis (10 minutes TTL)
    if verification_id:
        await redis.setex(f"auth_phone_vid:{user.id}", 600, verification_id)
        await redis.setex(f"auth_phone_vid:{formatted_phone}", 600, verification_id)
        await redis.setex(f"auth_phone_vid:{ten_digit}", 600, verification_id)
    
    logger.info(f"📱 Auth Phone OTP requested for {user.email} ({formatted_phone}) | MSG91 VID: {verification_id} | Fallback code: {code}")
    
    return MessageResponse(message=f"OTP sent successfully to {formatted_phone}")


@router.post("/phone/verify-otp", response_model=UserResponse)
async def verify_phone_otp(
    data: PhoneOTPVerify,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """Verify OTP and link mobile number to the authenticated user account."""
    clean_digits = "".join(c for c in str(data.phone) if c.isdigit())
    if len(clean_digits) < 10:
        raise BadRequestException("Invalid mobile number format")
    
    ten_digit = clean_digits[-10:]
    valid_formatted_phone = data.phone.strip()
    if not valid_formatted_phone.startswith("+"):
        valid_formatted_phone = f"+91{ten_digit}"
        
    is_valid = False
    from app.services.sms_service import sms_service

    # 1. Dev/Mock Mode Bypass
    if sms_service.mock_mode and data.code in ["123456", "000000"]:
        logger.info(f"🔑 Dev bypass OTP used for {user.email} ({valid_formatted_phone})")
        is_valid = True

    # 2. Verify via MSG91 using stored verification_id
    if not is_valid:
        vid_bytes = None
        for key in [f"auth_phone_vid:{user.id}", f"auth_phone_vid:{valid_formatted_phone}", f"auth_phone_vid:{ten_digit}"]:
            val = await redis.get(key)
            if val:
                vid_bytes = val
                break
                
        if vid_bytes:
            verification_id = vid_bytes.decode('utf-8') if isinstance(vid_bytes, bytes) else str(vid_bytes)
            is_valid = await sms_service.verify_otp(verification_id, data.code, mobile_number=valid_formatted_phone)
            if is_valid:
                logger.info(f"✅ MSG91 SMS OTP verified successfully for user {user.email} ({valid_formatted_phone})")

    # 3. Fallback check with local Redis OTP service
    if not is_valid:
        otp_service = OTPService(redis)
        for candidate in [data.phone.strip(), f"+91{ten_digit}", f"91{ten_digit}", ten_digit]:
            if await otp_service.verify_otp(f"phone:{user.id}:{candidate}", data.code):
                is_valid = True
                break
        if not is_valid:
            for candidate in [data.phone.strip(), f"+91{ten_digit}", ten_digit]:
                if await otp_service.verify_otp(candidate, data.code):
                    is_valid = True
                    break

    if not is_valid:
        raise BadRequestException("Invalid or expired OTP code")

    # Clean up verification IDs from Redis
    for key in [f"auth_phone_vid:{user.id}", f"auth_phone_vid:{valid_formatted_phone}", f"auth_phone_vid:{ten_digit}"]:
        await redis.delete(key)

    # Update user phone
    user.phone = valid_formatted_phone
    user.phone_verified = True
    await db.commit()
    await db.refresh(user)

    return UserResponse(
        id=str(user.id),
        email=user.email,
        phone=user.phone,
        phone_verified=user.phone_verified,
        role=user.role,
        is_active=user.is_active,
        last_login=str(user.last_login) if user.last_login else None,
        created_at=str(user.created_at),
    )

@router.post("/change-email", response_model=MessageResponse)
async def change_email(
    data: ChangeEmailRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """Change user email requiring old and new OTPs."""
    otp_service = OTPService(redis)
    
    # Verify old email OTP
    is_old_valid = await otp_service.verify_otp(user.email, data.old_email_otp)
    if not is_old_valid:
        raise BadRequestException("Invalid or expired OTP for current email")
        
    # Verify new email OTP
    is_new_valid = await otp_service.verify_otp(data.new_email, data.new_email_otp)
    if not is_new_valid:
        raise BadRequestException("Invalid or expired OTP for new email")
        
    # Check if new email already exists
    stmt = select(User).where(User.email == data.new_email)
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        raise BadRequestException("This email address is already registered")
        
    # Update email
    user.email = data.new_email
    await db.commit()
    
    return MessageResponse(message="Email updated successfully")
