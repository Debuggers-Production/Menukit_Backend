"""Dependency injection for API routes."""

import uuid
from typing import Optional

from fastapi import Depends, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.database.redis import get_redis
from app.core.security import verify_access_token
from app.core.exceptions import UnauthorizedException, ForbiddenException
from app.models.user import User
from app.services.auth_service import AuthService

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Get the current authenticated user from JWT token."""
    if not credentials:
        raise UnauthorizedException("Missing authentication token")

    payload = verify_access_token(credentials.credentials)
    if not payload:
        raise UnauthorizedException("Invalid or expired token")

    user_id = payload.get("sub")
    if not user_id:
        raise UnauthorizedException("Invalid token payload")

    auth_service = AuthService(db)
    user = await auth_service.get_user_by_id(uuid.UUID(user_id))

    if not user:
        raise UnauthorizedException("User not found")
    if not user.is_active:
        raise ForbiddenException("Account is disabled")

    return user


async def get_current_admin(
    user: User = Depends(get_current_user),
) -> User:
    """Ensure the current user is an admin."""
    if user.role != "admin":
        raise ForbiddenException("Admin access required")
    return user
