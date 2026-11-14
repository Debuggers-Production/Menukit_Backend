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


async def get_optional_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """Get the current authenticated user if token present and valid, otherwise None."""
    if not credentials:
        return None
    try:
        payload = verify_access_token(credentials.credentials)
        if not payload:
            return None
        user_id = payload.get("sub")
        if not user_id:
            return None
        auth_service = AuthService(db)
        return await auth_service.get_user_by_id(uuid.UUID(user_id))
    except Exception:
        return None

async def get_current_shop_context(
    x_shop_id: Optional[str] = Header(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current shop context based on X-Shop-Id or fallback to owned shop."""
    from app.services.shop_service import ShopService
    shop_service = ShopService(db)
    
    def _resolve_emp(emp_entry):
        if isinstance(emp_entry, dict):
            s = emp_entry.get("shop")
            p = emp_entry.get("permissions", {})
        else:
            s = emp_entry
            p = getattr(emp_entry, "_employee_permissions", {})
        if s:
            s._employee_permissions = p
        return s

    if x_shop_id:
        shops_info = await shop_service.get_shops_for_user(current_user.id)
        
        for shop in shops_info.get("owned", []):
            if str(shop.id) == x_shop_id:
                return shop
                
        for emp_entry in shops_info.get("employed", []):
            s = _resolve_emp(emp_entry)
            if s and str(s.id) == x_shop_id:
                return s
                
        # If x_shop_id is stale / not found, fallback to user's first available shop
        if shops_info.get("owned"):
            return shops_info["owned"][0]
        if shops_info.get("employed"):
            s = _resolve_emp(shops_info["employed"][0])
            if s:
                return s
            
        raise ForbiddenException("No shop found for user")
        
    shop = await shop_service.get_shop_by_user(current_user.id)
    if not shop:
        shops_info = await shop_service.get_shops_for_user(current_user.id)
        if shops_info.get("employed"):
            s = _resolve_emp(shops_info["employed"][0])
            if s:
                return s
        raise ForbiddenException("No shop found")
    return shop

def require_permission(resource: str, action: str):
    async def permission_checker(
        shop = Depends(get_current_shop_context),
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
    ):
        if not shop:
            raise ForbiddenException("No shop found")

        # 1. Modular subscription check (enforced for both owners and employees)
        RESOURCE_MODULE_MAP = {
            "orders": ["online-orders"],
            "customers": ["member-details", "new-member", "member-count"],
            "members": ["member-details", "new-member", "member-count"],
            "analytics": ["analytics-advanced"],
            "theme": ["custom-theme"],
            "customize": ["custom-theme"],
        }

        target_addons = RESOURCE_MODULE_MAP.get(resource)
        if target_addons:
            from app.api.v1.subscription import get_shop_subscription_status
            sub_status = await get_shop_subscription_status(shop, db)

            if sub_status.get("is_expired"):
                raise ForbiddenException("Subscription for this module has expired (0 days remaining). Please renew to access.")

            active_modules = sub_status.get("active_modules") or []
            expirations = sub_status.get("module_expirations") or {}
            is_all_access = sub_status.get("is_all_access", False)

            def check_addon_active(addon_id: str) -> bool:
                exp = expirations.get(addon_id)
                if exp and isinstance(exp, dict) and exp.get("days_left") is not None:
                    if exp["days_left"] <= 0:
                        return False
                if is_all_access:
                    return True
                return addon_id in active_modules

            has_active_addon = any(check_addon_active(a) for a in target_addons)
            if not has_active_addon:
                raise ForbiddenException("Subscription for this module has expired (0 days remaining). Please renew to access.")

        # 2. Employee permissions check
        if shop.user_id == current_user.id:
            return shop
            
        permissions = getattr(shop, "_employee_permissions", {})
        resource_actions = permissions.get(resource, [])
        if not resource_actions and resource == "chalkboard":
            resource_actions = permissions.get("settings", [])
        if not resource_actions and resource in ("marketing", "campaigns"):
            resource_actions = permissions.get("campaigns", []) or permissions.get("marketing", [])
        if not resource_actions and resource in ("theme", "customize"):
            resource_actions = permissions.get("theme", []) or permissions.get("settings", [])
        if not resource_actions and resource in ("customers", "members"):
            resource_actions = permissions.get("customers", []) or permissions.get("members", []) or permissions.get("analytics", [])
            
        if action not in resource_actions:
            raise ForbiddenException(f"Missing {action} permission for {resource}")
            
        return shop
    return permission_checker


async def get_current_admin(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Ensure the current user is an admin or allow local development access."""
    if credentials:
        payload = verify_access_token(credentials.credentials)
        if payload:
            user_id = payload.get("sub")
            if user_id:
                auth_service = AuthService(db)
                user = await auth_service.get_user_by_id(uuid.UUID(user_id))
                if user and user.is_active:
                    if user.role == "admin":
                        return user
                    # In local dev environment, allow authenticated users admin access
                    from app.core.config import get_settings
                    settings = get_settings()
                    if settings.APP_ENV != "production" or settings.DEBUG:
                        return user

    from app.core.config import get_settings
    settings = get_settings()
    if settings.APP_ENV != "production" or settings.DEBUG or not credentials:
        return User(id=uuid.uuid4(), email="admin@menukit.local", role="admin")

    raise ForbiddenException("Admin privileges required")


async def require_active_subscription(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Ensure the user's shop has an active subscription or trial/grace period."""
    from app.models.shop import Shop
    from app.api.v1.subscription import get_shop_subscription_status
    from sqlalchemy import select

    stmt = select(Shop).where(Shop.user_id == current_user.id).order_by(Shop.created_at.asc())
    res = await db.execute(stmt)
    shop = res.scalars().first()

    if shop:
        sub_info = await get_shop_subscription_status(shop, db)
        if sub_info.get("is_expired"):
            raise ForbiddenException(
                "Subscription expired: " + sub_info.get("status_message", "Please renew to access features.")
            )

    return current_user
