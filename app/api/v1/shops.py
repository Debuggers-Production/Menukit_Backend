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
    return _shop_to_response(shop)


@router.get("/me", response_model=ShopResponse)
async def get_my_shop(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current user's shop."""
    service = ShopService(db)
    shop = await service.get_shop_by_user(user.id)
    if not shop:
        return ShopResponse(
            id="", name="", slug="", is_active=False, created_at=""
        )
    return _shop_to_response(shop)


@router.put("/me", response_model=ShopResponse)
async def update_my_shop(
    data: ShopUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the current user's shop."""
    service = ShopService(db)
    shop = await service.update_shop(user.id, data.model_dump(exclude_unset=True))
    return _shop_to_response(shop)


@router.put("/me/theme", response_model=ThemeSettingsResponse)
async def update_theme(
    data: ThemeSettingsUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update shop theme settings."""
    service = ShopService(db)
    theme = await service.update_theme(user.id, data.model_dump(exclude_none=True))
    return ThemeSettingsResponse(
        id=str(theme.id),
        theme=theme.theme,
        primary_color=theme.primary_color,
        secondary_color=theme.secondary_color,
        font_family=theme.font_family,
        layout=theme.layout,
        banner_style=theme.banner_style,
    )


@router.put("/me/settings", response_model=ShopSettingsResponse)
async def update_settings(
    data: ShopSettingsUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update shop configuration settings."""
    service = ShopService(db)
    settings = await service.update_settings(user.id, data.model_dump(exclude_none=True))
    return ShopSettingsResponse(
        id=str(settings.id),
        currency=settings.currency,
        language=settings.language,
        show_prices=settings.show_prices,
        show_offers=settings.show_offers,
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
        )

    settings_resp = None
    if shop.settings:
        settings_resp = ShopSettingsResponse(
            id=str(shop.settings.id),
            currency=shop.settings.currency,
            language=shop.settings.language,
            show_prices=shop.settings.show_prices,
            show_offers=shop.settings.show_offers,
        )

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
        settings=settings_resp,
        theme=theme_resp,
        created_at=str(shop.created_at),
    )
