"""Admin API endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.core.deps import get_current_admin
from app.services.shop_service import ShopService
from app.services.analytics_service import AnalyticsService
from app.models.user import User

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/stats")
async def get_platform_stats(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get platform-wide statistics."""
    service = AnalyticsService(db)
    return await service.get_platform_stats()


@router.get("/restaurants")
async def get_all_restaurants(
    page: int = 1,
    page_size: int = 20,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get paginated list of all restaurants."""
    service = ShopService(db)
    result = await service.get_all_shops(page, page_size)
    
    # Format response
    from app.api.v1.shops import _shop_to_response
    items = [_shop_to_response(shop).model_dump() for shop in result["items"]]
    result["items"] = items
    
    return result


@router.put("/restaurants/{shop_id}/toggle")
async def toggle_restaurant_status(
    shop_id: str,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Enable or disable a restaurant."""
    import uuid
    service = ShopService(db)
    shop = await service.toggle_shop(uuid.UUID(shop_id))
    
    from app.api.v1.shops import _shop_to_response
    return _shop_to_response(shop)
