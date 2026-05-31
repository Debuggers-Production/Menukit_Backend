"""Menu item management API endpoints."""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.core.deps import get_current_user
from app.schemas.menu_item import (
    MenuItemCreate, MenuItemUpdate, MenuItemReorder,
    MenuItemResponse, MenuImageResponse,
)
from app.schemas.common import MessageResponse
from app.services.menu_service import MenuService
from app.services.shop_service import ShopService
from app.models.user import User

router = APIRouter(prefix="/menu-items", tags=["Menu Item Management"])


@router.post("", response_model=MenuItemResponse)
async def create_menu_item(
    data: MenuItemCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new menu item."""
    service = MenuService(db)
    item = await service.create_menu_item(user.id, data.model_dump())
    return _item_response(item)


@router.get("", response_model=List[MenuItemResponse])
async def get_menu_items(
    category_id: Optional[str] = Query(None),
    food_type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all menu items with optional filters."""
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_user(user.id)
    if not shop:
        return []

    service = MenuService(db)
    items = await service.get_menu_items(
        shop.id,
        category_id=uuid.UUID(category_id) if category_id else None,
        food_type=food_type,
        search=search,
    )
    
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"get_menu_items retrieved {len(items)} items")
    
    return [_item_response(i) for i in items]


@router.get("/{item_id}", response_model=MenuItemResponse)
async def get_menu_item(
    item_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single menu item."""
    service = MenuService(db)
    item = await service.get_menu_item(uuid.UUID(item_id))
    if not item:
        from app.core.exceptions import NotFoundException
        raise NotFoundException("Menu item not found")
        
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"get_menu_item retrieved item {item_id}")
        
    return _item_response(item)


@router.put("/{item_id}", response_model=MenuItemResponse)
async def update_menu_item(
    item_id: str,
    data: MenuItemUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a menu item."""
    service = MenuService(db)
    item = await service.update_menu_item(user.id, uuid.UUID(item_id), data.model_dump(exclude_none=True))
    return _item_response(item)


@router.delete("/{item_id}", response_model=MessageResponse)
async def delete_menu_item(
    item_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a menu item."""
    service = MenuService(db)
    await service.delete_menu_item(user.id, uuid.UUID(item_id))
    return MessageResponse(message="Menu item deleted successfully")


@router.put("/reorder/batch", response_model=MessageResponse)
async def reorder_items(
    data: MenuItemReorder,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reorder menu items."""
    service = MenuService(db)
    await service.reorder_menu_items(user.id, data.order)
    return MessageResponse(message="Items reordered successfully")


@router.delete("/{item_id}/images/{image_id}", response_model=MessageResponse)
async def delete_menu_image(
    item_id: str,
    image_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a menu item image."""
    service = MenuService(db)
    await service.delete_menu_image(user.id, uuid.UUID(item_id), uuid.UUID(image_id))
    return MessageResponse(message="Image deleted successfully")


@router.put("/{item_id}/images/{image_id}/primary", response_model=MessageResponse)
async def set_primary_image(
    item_id: str,
    image_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set a menu item image as primary."""
    service = MenuService(db)
    await service.set_primary_menu_image(user.id, uuid.UUID(item_id), uuid.UUID(image_id))
    return MessageResponse(message="Primary image updated successfully")


from sqlalchemy import inspect

def _item_response(item) -> MenuItemResponse:
    """Convert MenuItem model to response."""
    image_url = None
    thumbnail_url = None
    images_list = []
    state = inspect(item)
    if "images" not in state.unloaded and hasattr(item, "images") and item.images:
        # Find the primary images, and use the newest one. If none, use the newest uploaded image.
        primaries = [img for img in item.images if img.is_primary]
        if primaries:
            primary = sorted(primaries, key=lambda x: x.created_at, reverse=True)[0]
        else:
            primary = sorted(item.images, key=lambda x: x.created_at, reverse=True)[0]
            
        image_url = primary.image_url
        thumbnail_url = primary.thumbnail_url
        
        images_list = [
            MenuImageResponse(
                id=str(img.id),
                image_url=img.image_url,
                thumbnail_url=img.thumbnail_url,
                is_primary=img.is_primary,
                display_order=img.display_order
            ) for img in sorted(item.images, key=lambda x: (not x.is_primary, x.display_order))
        ]

    return MenuItemResponse(
        id=str(item.id),
        category_id=str(item.category_id),
        name=item.name,
        description=item.description,
        price=str(item.price),
        offer_price=str(item.offer_price) if item.offer_price else None,
        food_type=item.food_type,
        is_bestseller=item.is_bestseller,
        is_highlighted=item.is_highlighted,
        is_available=item.is_available,
        display_order=item.display_order,
        image_url=image_url,
        thumbnail_url=thumbnail_url,
        images=images_list,
        created_at=str(item.created_at),
    )
