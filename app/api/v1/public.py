"""Public API endpoints for customer menu access."""

import uuid
from typing import List, Optional
from pydantic import BaseModel

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.schemas.shop import ShopResponse
from app.schemas.category import CategoryResponse
from app.schemas.menu_item import MenuItemResponse
from app.schemas.common import MessageResponse
from app.services.shop_service import ShopService
from app.services.menu_service import MenuService
from app.services.analytics_service import AnalyticsService
from app.core.exceptions import NotFoundException
from app.api.v1.shops import _shop_to_response
from app.api.v1.categories import _category_response
from app.api.v1.menu_items import _item_response

class PublicCategoryResponse(CategoryResponse):
    """Public category response with menu items."""
    items: List[MenuItemResponse] = []


router = APIRouter(prefix="/public/shop/{shop_id}", tags=["Public Menu"])


class ScanRequest(BaseModel):
    referrer: Optional[str] = None


class ViewRequest(BaseModel):
    item_id: Optional[str] = None
    category_id: Optional[str] = None


class SearchRequest(BaseModel):
    term: str
    result_count: int


@router.get("", response_model=ShopResponse)
async def get_public_shop(
    shop_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get shop details for public menu."""
    service = ShopService(db)
    shop = await service.get_shop_by_id(shop_id)
    if not shop:
        raise NotFoundException("Restaurant not found")
    return _shop_to_response(shop)


@router.get("/menu", response_model=List[PublicCategoryResponse])
async def get_public_menu(
    shop_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get full menu organized by categories."""
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_id(shop_id)
    if not shop:
        raise NotFoundException("Restaurant not found")

    menu_service = MenuService(db)
    categories = await menu_service.get_categories(shop.id)
    
    # Filter out inactive categories
    categories = [cat for cat in categories if cat.is_active]
    
    # We load items for each category. In a real app we might optimize this query
    result = []
    for cat in categories:
        items = await menu_service.get_menu_items(shop.id, category_id=cat.id)
        cat_resp = _category_response(cat)
        # Add items to category dict
        cat_dict = cat_resp.model_dump()
        cat_dict["items"] = [_item_response(i).model_dump() for i in items]
        result.append(cat_dict)
        
    return result


@router.post("/scan", response_model=MessageResponse)
async def record_scan(
    shop_id: uuid.UUID,
    request: Request,
    data: ScanRequest = None,
    db: AsyncSession = Depends(get_db),
):
    """Record a QR scan for analytics."""
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_id(shop_id)
    if not shop:
        raise NotFoundException("Restaurant not found")

    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent", "")[:500]
    ref = data.referrer if data else None

    analytics = AnalyticsService(db)
    await analytics.record_qr_scan(shop.id, ip=ip, ua=ua, ref=ref)
    
    return MessageResponse(message="Scan recorded")


@router.post("/view", response_model=MessageResponse)
async def record_view(
    shop_id: uuid.UUID,
    request: Request,
    data: ViewRequest = None,
    db: AsyncSession = Depends(get_db),
):
    """Record a menu item or category view."""
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_id(shop_id)
    if not shop:
        raise NotFoundException("Restaurant not found")

    ip = request.client.host if request.client else None
    
    item_id = uuid.UUID(data.item_id) if data and data.item_id else None
    cat_id = uuid.UUID(data.category_id) if data and data.category_id else None

    analytics = AnalyticsService(db)
    await analytics.record_menu_view(shop.id, item_id=item_id, category_id=cat_id, ip=ip)
    
    return MessageResponse(message="View recorded")


@router.post("/search", response_model=MessageResponse)
async def record_search(
    shop_id: uuid.UUID,
    data: SearchRequest,
    db: AsyncSession = Depends(get_db),
):
    """Record a search query."""
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_id(shop_id)
    if not shop:
        raise NotFoundException("Restaurant not found")

    analytics = AnalyticsService(db)
    await analytics.record_search(shop.id, data.term, data.result_count)
    
    return MessageResponse(message="Search recorded")
