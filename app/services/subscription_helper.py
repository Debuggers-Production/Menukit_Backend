"""Subscription feature permission helper module."""

import uuid
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

DEFAULT_THEME_DICT = {
    "theme": "light",
    "primary_color": "#f97316",
    "secondary_color": "#1e293b",
    "discount_card_style": "modern",
    "menu_item_style": "default",
    "font_family": "Inter",
    "theme_scope": "public"
}


async def get_shop_subscription_permissions(shop_id: uuid.UUID, db: AsyncSession) -> Dict[str, Any]:
    """Returns boolean dictionary of active feature permissions for a shop based on subscription."""
    from app.models.shop import Shop
    from app.api.v1.subscription import get_shop_subscription_status

    stmt = select(Shop).where(Shop.id == shop_id)
    res = await db.execute(stmt)
    shop = res.scalar_one_or_none()

    if not shop:
        return {
            "is_active": False,
            "is_expired": True,
            "online_orders": False,
            "custom_theme": False,
            "member_count": False,
            "member_details": False,
            "search_data": False,
            "analytics_advanced": False,
            "analytics_customer": False
        }

    sub_status = await get_shop_subscription_status(shop, db)
    
    if sub_status.get("is_expired"):
        return {
            "is_active": False,
            "is_expired": True,
            "online_orders": False,
            "custom_theme": False,
            "member_count": False,
            "member_details": False,
            "search_data": False,
            "analytics_advanced": False,
            "analytics_customer": False
        }

    active_mods = sub_status.get("active_modules") or []
    is_all = sub_status.get("is_all_access", False)

    def has_mod(mod_name: str) -> bool:
        return is_all or (mod_name in active_mods)

    return {
        "is_active": True,
        "is_expired": False,
        "online_orders": has_mod("online-orders"),
        "custom_theme": has_mod("custom-theme"),
        "member_count": has_mod("member-count"),
        "member_details": has_mod("member-details"),
        "search_data": has_mod("search-data"),
        "analytics_advanced": has_mod("analytics-advanced") or has_mod("analytics-advanced-filters"),
        "analytics_customer": has_mod("analytics-advanced") or has_mod("analytics-customer-insights")
    }
