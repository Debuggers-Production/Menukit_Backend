from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.session import get_db
from app.database.redis import get_redis
from app.core.deps import get_current_user
from app.core.exceptions import BadRequestException, RateLimitException
from app.schemas.auth import OTPRequest, OTPVerify, TokenResponse, RefreshTokenRequest, UserResponse
from app.schemas.common import MessageResponse
from app.services.otp_service import OTPService
from app.services.email_service import EmailService
from app.services.auth_service import AuthService
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/request-otp", response_model=MessageResponse)
async def request_otp(
    data: OTPRequest,
    redis=Depends(get_redis),
):
    """Send OTP to the provided email address."""
    otp_service = OTPService(redis)
    code = await otp_service.create_otp(data.email)

    if code is None:
        raise RateLimitException("Too many OTP requests. Please try again later.")

    email_service = EmailService()
    sent = await email_service.send_otp_email(data.email, code)

    if not sent:
        raise BadRequestException("Failed to send OTP email. Please try again.")

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
        role=user.role,
        is_active=user.is_active,
        last_login=str(user.last_login) if user.last_login else None,
        created_at=str(user.created_at),
    )
