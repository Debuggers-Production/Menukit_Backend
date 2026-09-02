"""Shop management API endpoints."""

import uuid
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.database.session import get_db
from app.core.deps import get_current_user, require_permission
from app.schemas.shop import (
    ShopCreate, ShopUpdate, ShopResponse,
    ShopSettingsUpdate, ShopSettingsResponse,
    ThemeSettingsUpdate, ThemeSettingsResponse,
    RazorpayBankAccountUpdateRequest,
    RazorpayLinkedAccountCreateRequest,
)
from app.services.shop_service import ShopService
from app.models.user import User

router = APIRouter(prefix="/shops", tags=["Shop Management"])


@router.post("", response_model=ShopResponse)
async def create_shop(
    data: ShopCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new shop profile (strictly limited to 1 shop per user)."""
    service = ShopService(db)
    shops_info = await service.get_shops_for_user(user.id)
    if len(shops_info["owned"]) >= 1:
        raise HTTPException(
            status_code=400,
            detail="Branch creation is currently disabled. Each user is limited to 1 shop."
        )

    shop = await service.create_shop(user.id, data.model_dump(exclude_none=True))
    await db.commit()
    return _shop_to_response(shop)


@router.get("/my-shops")
async def get_my_shops(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all shops the user has access to (owned and employed)."""
    service = ShopService(db)
    shops_info = await service.get_shops_for_user(user.id)
    
    # Format the response
    owned = [_shop_to_response(s).model_dump() for s in shops_info["owned"]]
    employed = []
    for emp in shops_info["employed"]:
        resp = _shop_to_response(emp["shop"]).model_dump()
        resp["employee_permissions"] = emp["permissions"]
        employed.append(resp)
        
    return {
        "owned": owned,
        "employed": employed
    }


@router.get("/brand/{user_id}/branches")
async def get_brand_branches(
    user_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get all public branches for a given brand (user)."""
    service = ShopService(db)
    try:
        user_uuid = uuid.UUID(user_id)
        shops_info = await service.get_shops_for_user(user_uuid)
        active_owned = [s for s in shops_info["owned"] if s.is_active]
        return [_shop_to_response(s) for s in active_owned]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid brand ID")


@router.get("/me", response_model=ShopResponse)
async def get_my_shop(
    x_shop_id: Optional[str] = Header(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current user's shop with subscription-based feature data filtering."""
    service = ShopService(db)
    
    employee_permissions = None
    if x_shop_id:
        shops_info = await service.get_shops_for_user(user.id)
        shop = None
        for s in shops_info["owned"]:
            if str(s.id) == x_shop_id:
                shop = s
                break
        if not shop:
            for emp in shops_info["employed"]:
                if str(emp["shop"].id) == x_shop_id:
                    shop = emp["shop"]
                    employee_permissions = emp["permissions"]
                    break
    else:
        shop = await service.get_shop_by_user(user.id)
        if not shop:
            shops_info = await service.get_shops_for_user(user.id)
            if shops_info["employed"]:
                emp = shops_info["employed"][0]
                shop = emp["shop"]
                employee_permissions = emp["permissions"]
        
    if not shop:
        return ShopResponse(
            id="", name="", slug="", is_active=False, created_at=""
        )
        
    response = await format_shop_response_with_subscription_checks(shop, db)
    if employee_permissions is not None:
        response.employee_permissions = employee_permissions
    return response


@router.put("/me", response_model=ShopResponse)
async def update_my_shop(
    data: ShopUpdate,
    shop = Depends(require_permission("settings", "write")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the current user's shop."""
    service = ShopService(db)
    shop_updated = await service.update_shop(shop.id, user.id, data.model_dump(exclude_unset=True))
    await db.commit()
    return await format_shop_response_with_subscription_checks(shop_updated, db)


@router.put("/me/theme", response_model=ThemeSettingsResponse)
async def update_theme(
    data: ThemeSettingsUpdate,
    shop = Depends(require_permission("settings", "write")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update shop theme settings, enforcing subscription check."""
    from app.services.subscription_helper import get_shop_subscription_permissions
    perms = await get_shop_subscription_permissions(shop.id, db)
    if not perms["custom_theme"]:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=403,
            detail="Custom Theme Studio is locked due to expired subscription. Please renew your subscription to save custom themes."
        )
            
    theme = await ShopService(db).update_theme(shop.id, user.id, data.model_dump(exclude_none=True))
    await db.commit()
    return ThemeSettingsResponse(
        id=str(theme.id),
        theme=theme.theme,
        primary_color=theme.primary_color,
        secondary_color=theme.secondary_color,
        font_family=theme.font_family,
        layout=theme.layout,
        banner_style=theme.banner_style,
        theme_scope=theme.theme_scope,
        discount_card_style=theme.discount_card_style,
        menu_item_style=theme.menu_item_style,
        border_radius=theme.border_radius,
    )


@router.put("/me/settings", response_model=ShopSettingsResponse)
async def update_settings(
    data: ShopSettingsUpdate,
    shop = Depends(require_permission("settings", "write")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update shop settings."""
    service = ShopService(db)
    settings = await service.update_settings(shop.id, user.id, data.model_dump(exclude_unset=True))
    await db.commit()

    # Invalidate public shop cache
    try:
        from app.database.redis import get_redis
        r_client = await get_redis()
        await r_client.delete(f"public:shop:{str(shop.id)}")
    except Exception:
        pass

    return ShopSettingsResponse.model_validate(settings)



@router.patch("/me/razorpay/bank-account")
async def update_razorpay_bank_account(
    data: RazorpayBankAccountUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update Razorpay Route linked account bank details."""
    service = ShopService(db)
    result = await service.update_razorpay_bank_account(user.id, data)
    await db.commit()
    return result


@router.post("/me/razorpay/linked-account")
async def create_razorpay_linked_account(
    data: RazorpayLinkedAccountCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new Razorpay Route linked account with bank details."""
    service = ShopService(db)
    result = await service.create_razorpay_linked_account(user.id, data)
    await db.commit()
    return result


@router.get("/me/razorpay/status")
async def get_razorpay_account_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch current Razorpay Route verification status."""
    service = ShopService(db)
    result = await service.get_razorpay_account_status(user.id)
    await db.commit()
    return result


async def format_shop_response_with_subscription_checks(shop, db: AsyncSession) -> ShopResponse:
    """Convert Shop model to response schema enforcing subscription level feature permissions."""
    from app.services.subscription_helper import get_shop_subscription_permissions
    perms = await get_shop_subscription_permissions(shop.id, db)
    
    theme_resp = None
    if shop.theme:
        if perms["custom_theme"]:
            theme_resp = ThemeSettingsResponse(
                id=str(shop.theme.id),
                theme=shop.theme.theme,
                primary_color=shop.theme.primary_color,
                secondary_color=shop.theme.secondary_color,
                font_family=shop.theme.font_family,
                layout=shop.theme.layout,
                banner_style=shop.theme.banner_style,
                theme_scope=shop.theme.theme_scope,
                discount_card_style=shop.theme.discount_card_style,
                menu_item_style=shop.theme.menu_item_style,
                border_radius=shop.theme.border_radius,
            )
        else:
            # Automatic fallback to DEFAULT theme when custom_theme is locked/expired
            theme_resp = ThemeSettingsResponse(
                id=str(shop.theme.id),
                theme="light",
                primary_color="#f97316",
                secondary_color="#1e293b",
                font_family="Inter",
                layout=getattr(shop.theme, "layout", "standard") or "standard",
                banner_style=getattr(shop.theme, "banner_style", "hero") or "hero",
                theme_scope="public",
                discount_card_style="modern",
                menu_item_style="default",
                border_radius="smooth",
            )

    settings_resp = None
    if shop.settings:
        settings_dict = ShopSettingsResponse.model_validate(shop.settings).model_dump()
        if not perms["online_orders"]:
            # Automatic disable takeaway and delivery if online_orders is locked/expired
            settings_dict["allow_takeaway"] = False
            settings_dict["allow_delivery"] = False
            settings_dict["takeaway_enabled"] = False
            settings_dict["delivery_enabled"] = False
        settings_resp = ShopSettingsResponse(**settings_dict)


    return ShopResponse(
        id=str(shop.id),
        user_id=str(shop.user_id) if shop.user_id else None,
        name=shop.name,
        slug=shop.slug,
        description=shop.description,
        welcome_message=shop.welcome_message,
        logo_url=shop.logo_url,
        banner_url=shop.banner_url,
        phone=shop.phone,
        whatsapp=shop.whatsapp,
        address=shop.address,
        opening_time=shop.opening_time,
        closing_time=shop.closing_time,
        is_active=shop.is_active,
        latitude=shop.latitude,
        longitude=shop.longitude,
        google_review_link=shop.google_review_link,
        review_widget_code=shop.review_widget_code,
        settings=settings_resp,
        theme=theme_resp,
        created_at=str(shop.created_at),
    )


def _shop_to_response(shop) -> ShopResponse:
    """Convert Shop model to response schema."""
    theme_resp = None
    if shop.theme:
        theme_resp = ThemeSettingsResponse(
            id=str(shop.theme.id),
            theme=shop.theme.theme,
            primary_color=shop.theme.primary_color,
            secondary_color=shop.theme.secondary_color,
            font_family=shop.theme.font_family,
            layout=shop.theme.layout,
            banner_style=shop.theme.banner_style,
            theme_scope=shop.theme.theme_scope,
            discount_card_style=shop.theme.discount_card_style,
            menu_item_style=shop.theme.menu_item_style,
            border_radius=shop.theme.border_radius,
        )

    settings_resp = None
    if shop.settings:
        settings_resp = ShopSettingsResponse.model_validate(shop.settings)

    return ShopResponse(
        id=str(shop.id),
        user_id=str(shop.user_id) if shop.user_id else None,
        name=shop.name,
        slug=shop.slug,
        description=shop.description,
        welcome_message=shop.welcome_message,
        logo_url=shop.logo_url,
        banner_url=shop.banner_url,
        phone=shop.phone,
        whatsapp=shop.whatsapp,
        address=shop.address,
        opening_time=shop.opening_time,
        closing_time=shop.closing_time,
        is_active=shop.is_active,
        latitude=shop.latitude,
        longitude=shop.longitude,
        google_review_link=shop.google_review_link,
        review_widget_code=shop.review_widget_code,
        settings=settings_resp,
        theme=theme_resp,
        created_at=str(shop.created_at),
    )

