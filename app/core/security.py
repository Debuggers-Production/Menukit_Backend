"""JWT security utilities for authentication."""

from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import jwt, JWTError
from app.core.config import get_settings

settings = get_settings()


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_customer_token(mobile_number: str) -> str:
    """Create a long-lived JWT token for a verified customer."""
    expire = datetime.now(timezone.utc) + timedelta(days=365) # 1 year expiration
    to_encode = {"sub": mobile_number, "type": "customer_access", "exp": expire}
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(data: dict) -> str:
    """Create a JWT refresh token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """Decode and validate a JWT token."""
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except JWTError:
        return None


def verify_access_token(token: str) -> Optional[dict]:
    """Verify an access token and return payload."""
    payload = decode_token(token)
    if payload and payload.get("type") == "access":
        return payload
    return None


def verify_customer_token(token: str) -> Optional[str]:
    """Verify a customer token and return the mobile number."""
    payload = decode_token(token)
    if payload and payload.get("type") == "customer_access":
        return payload.get("sub")
    return None


def verify_refresh_token(token: str) -> Optional[dict]:
    """Verify a refresh token and return payload."""
    payload = decode_token(token)
    if payload and payload.get("type") == "refresh":
        return payload
    return None
