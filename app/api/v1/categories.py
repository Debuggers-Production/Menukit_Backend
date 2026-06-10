"""Category management API endpoints."""

import uuid
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.core.deps import get_current_user
from app.schemas.category import CategoryCreate, CategoryUpdate, CategoryReorder, CategoryResponse
from app.schemas.common import MessageResponse
from app.services.menu_service import MenuService
from app.services.shop_service import ShopService
from app.models.user import User

router = APIRouter(prefix="/categories", tags=["Category Management"])


@router.post("", response_model=CategoryResponse)
async def create_category(
    data: CategoryCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new menu category."""
    service = MenuService(db)
    category = await service.create_category(user.id, data.model_dump())
    return _category_response(category)


@router.get("", response_model=List[CategoryResponse])
async def get_categories(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all categories for the user's shop."""
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_user(user.id)
    if not shop:
        return []

    service = MenuService(db)
    categories = await service.get_categories(shop.id)
    return [_category_response(c) for c in categories]


@router.put("/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: str,
    data: CategoryUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a category."""
    service = MenuService(db)
    category = await service.update_category(user.id, uuid.UUID(category_id), data.model_dump(exclude_none=True))
    return _category_response(category)


@router.delete("/all", response_model=MessageResponse)
async def delete_all_categories(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete ALL categories and their items for the user's shop."""
    service = MenuService(db)
    await service.delete_all_categories(user.id)
    return MessageResponse(message="All categories deleted successfully")


@router.delete("/{category_id}", response_model=MessageResponse)
async def delete_category(
    category_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a category and all its menu items."""
    service = MenuService(db)
    await service.delete_category(user.id, uuid.UUID(category_id))
    return MessageResponse(message="Category deleted successfully")


@router.put("/reorder/batch", response_model=MessageResponse)
async def reorder_categories(
    data: CategoryReorder,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reorder categories."""
    service = MenuService(db)
    await service.reorder_categories(user.id, data.order)
    return MessageResponse(message="Categories reordered successfully")


from sqlalchemy import inspect

def _category_response(category) -> CategoryResponse:
    """Convert Category model to response."""
    state = inspect(category)
    item_count = 0
    if "menu_items" not in state.unloaded:
        item_count = len(category.menu_items) if category.menu_items else 0
    return CategoryResponse(
        id=str(category.id),
        name=category.name,
        image_url=category.image_url,
        display_order=category.display_order,
        is_active=category.is_active,
        item_count=item_count,
        created_at=str(category.created_at),
    )
