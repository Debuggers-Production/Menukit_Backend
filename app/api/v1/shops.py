"""Shop management API endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.core.deps import get_current_user
from app.schemas.shop import (
    ShopCreate, ShopUpdate, ShopResponse,
    ShopSettingsUpdate, ShopSettingsResponse,
    ThemeSettingsUpdate, ThemeSettingsResponse,
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
    """Create a new shop profile."""
    service = ShopService(db)
    shop = await service.create_shop(user.id, data.model_dump(exclude_none=True))
    await db.commit()
    return _shop_to_response(shop)


@router.get("/me", response_model=ShopResponse)
async def get_my_shop(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current user's shop with subscription-based feature data filtering."""
    service = ShopService(db)
    shop = await service.get_shop_by_user(user.id)
    if not shop:
        return ShopResponse(
            id="", name="", slug="", is_active=False, created_at=""
        )
    return await format_shop_response_with_subscription_checks(shop, db)


@router.put("/me", response_model=ShopResponse)
async def update_my_shop(
    data: ShopUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the current user's shop."""
    service = ShopService(db)
    shop = await service.update_shop(user.id, data.model_dump(exclude_unset=True))
    await db.commit()
    return await format_shop_response_with_subscription_checks(shop, db)


@router.put("/me/theme", response_model=ThemeSettingsResponse)
async def update_theme(
    data: ThemeSettingsUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update shop theme settings, enforcing subscription check."""
    service = ShopService(db)
    shop = await service.get_shop_by_user(user.id)
    if shop:
        from app.services.subscription_helper import get_shop_subscription_permissions
        perms = await get_shop_subscription_permissions(shop.id, db)
        if not perms["custom_theme"]:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=403,
                detail="Custom Theme Studio is locked due to expired subscription. Please renew your subscription to save custom themes."
            )
            
    theme = await service.update_theme(user.id, data.model_dump(exclude_none=True))
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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update shop behavior settings."""
    service = ShopService(db)
    settings = await service.update_settings(user.id, data.model_dump(exclude_none=True))
    await db.commit()
    return ShopSettingsResponse.model_validate(settings)


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
        settings_resp = ShopSettingsResponse(**settings_dict)

    return ShopResponse(
        id=str(shop.id),
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

