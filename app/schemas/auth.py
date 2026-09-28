"""Authentication schemas."""

from pydantic import BaseModel, EmailStr, field_validator


class OTPRequest(BaseModel):
    """Request OTP for email."""
    email: EmailStr

    @field_validator('email', mode='before')
    @classmethod
    def lowercase_email(cls, v: str) -> str:
        if isinstance(v, str):
            return v.strip().lower()
        return v


class OTPVerify(BaseModel):
    """Verify OTP code."""
    email: EmailStr
    code: str

    @field_validator('email', mode='before')
    @classmethod
    def lowercase_email(cls, v: str) -> str:
        if isinstance(v, str):
            return v.strip().lower()
        return v


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
    phone: str | None = None
    phone_verified: bool = False
    role: str
    is_active: bool
    last_login: str | None = None
    created_at: str

    class Config:
        from_attributes = True

class PhoneOTPRequest(BaseModel):
    """Request OTP for mobile number verification."""
    phone: str
    country_code: str = "+91"

class PhoneOTPVerify(BaseModel):
    """Verify OTP for mobile number."""
    phone: str
    code: str

class ChangeEmailRequest(BaseModel):
    """Change email request with OTPs."""
    old_email_otp: str
    new_email: EmailStr
    new_email_otp: str
