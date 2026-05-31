"""Authentication schemas."""

from pydantic import BaseModel, EmailStr


class OTPRequest(BaseModel):
    """Request OTP for email."""
    email: EmailStr


class OTPVerify(BaseModel):
    """Verify OTP code."""
    email: EmailStr
    code: str


class TokenResponse(BaseModel):
    """JWT token response."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshTokenRequest(BaseModel):
    """Refresh token request."""
    refresh_token: str


class UserResponse(BaseModel):
    """User profile response."""
    id: str
    email: str
    role: str
    is_active: bool
    last_login: str | None = None
    created_at: str

    class Config:
        from_attributes = True
