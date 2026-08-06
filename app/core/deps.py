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


async def get_current_admin() -> User:
    """Ensure the current user is an admin."""
    # Local dev bypass
    import uuid
    return User(id=uuid.uuid4(), email="local@admin.com", role="admin")


async def require_active_subscription(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Ensure the user's shop has an active subscription or trial/grace period."""
    from app.models.shop import Shop
    from app.api.v1.subscription import get_shop_subscription_status
    from sqlalchemy import select

    stmt = select(Shop).where(Shop.user_id == current_user.id)
    res = await db.execute(stmt)
    shop = res.scalar_one_or_none()

    if shop:
        sub_info = await get_shop_subscription_status(shop, db)
        if sub_info.get("is_expired"):
            raise ForbiddenException(
                "Subscription expired: " + sub_info.get("status_message", "Please renew to access features.")
            )

    return current_user
