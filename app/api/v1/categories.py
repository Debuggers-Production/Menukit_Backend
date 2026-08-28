"""Category management API endpoints."""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.database.redis import get_redis
from app.core.deps import get_current_user, require_permission
from app.core.exceptions import RateLimitException
from app.schemas.category import CategoryCreate, CategoryUpdate, CategoryReorder, CategoryResponse
from app.schemas.common import MessageResponse
from app.services.menu_service import MenuService
from app.services.shop_service import ShopService
from app.services.otp_service import OTPService
from app.services.email_service import EmailService
from app.models.user import User

router = APIRouter(prefix="/categories", tags=["Category Management"])


@router.post("", response_model=CategoryResponse)
async def create_category(
    data: CategoryCreate,
    shop = Depends(require_permission("menu_categories", "write")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new menu category."""
    service = MenuService(db)
    category = await service.create_category(shop.id, user.id, data.model_dump())
    await db.commit()
    from app.database.redis import invalidate_shop_cache
    await invalidate_shop_cache(shop.id)
    return _category_response(category)


@router.get("", response_model=List[CategoryResponse])
async def get_categories(
    response: Response,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=1000),
    search: Optional[str] = Query(None),
    shop = Depends(require_permission("menu_categories", "read")),
    db: AsyncSession = Depends(get_db),
):
    """Get all categories for the user's shop with pagination and backend search."""
    service = MenuService(db)
    categories, total_count, has_more = await service.get_categories(shop.id, skip=skip, limit=limit, search=search)
    response.headers["x-total-count"] = str(total_count)
    response.headers["x-has-more"] = "true" if has_more else "false"
    return [_category_response(c) for c in categories]


@router.put("/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: str,
    data: CategoryUpdate,
    shop = Depends(require_permission("menu_categories", "write")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a category."""
    service = MenuService(db)
    category = await service.update_category(shop.id, user.id, uuid.UUID(category_id), data.model_dump(exclude_unset=True))
    await db.commit()
    from app.database.redis import invalidate_shop_cache
    await invalidate_shop_cache(shop.id)
    return _category_response(category)


@router.post("/request-deletion-otp", response_model=MessageResponse)
async def request_deletion_otp(
    target: str = Query("categories", description="Target resource being deleted"),
    user: User = Depends(get_current_user),
    redis=Depends(get_redis),
):
    """Request an OTP for confirming bulk deletion."""
    otp_service = OTPService(redis)
    code = await otp_service.create_otp(user.email, rate_limit_type="deletion")
    if code is None:
        raise RateLimitException("Too many OTP requests. Please try again later.")

    email_service = EmailService()
    await email_service.send_deletion_otp_email(user.email, code, target=target)
    return MessageResponse(message=f"Deletion OTP code has been sent to {user.email}")


@router.delete("/all", response_model=MessageResponse)
async def delete_all_categories(
    code: str = Query(..., description="OTP verification code received via email"),
    shop = Depends(require_permission("menu_categories", "write")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """Delete ALL categories and their items for the user's shop after OTP verification."""
    otp_service = OTPService(redis)
    is_valid = await otp_service.verify_otp(user.email, code)
    if not is_valid:
        raise HTTPException(status_code=400, detail="Invalid or expired deletion OTP code")

    service = MenuService(db)
    await service.delete_all_categories(shop.id, user.id)
    await db.commit()
    from app.database.redis import invalidate_shop_cache
    await invalidate_shop_cache(shop.id)
    return MessageResponse(message="All categories deleted successfully")


@router.delete("/{category_id}", response_model=MessageResponse)
async def delete_category(
    category_id: str,
    code: str = Query(..., description="OTP verification code received via email"),
    shop = Depends(require_permission("menu_categories", "write")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """Delete a category and all its menu items after OTP verification."""
    otp_service = OTPService(redis)
    is_valid = await otp_service.verify_otp(user.email, code)
    if not is_valid:
        raise HTTPException(status_code=400, detail="Invalid or expired deletion OTP code")

    service = MenuService(db)
    await service.delete_category(shop.id, user.id, uuid.UUID(category_id))
    await db.commit()
    from app.database.redis import invalidate_shop_cache
    await invalidate_shop_cache(shop.id)
    return MessageResponse(message="Category deleted successfully")


@router.put("/reorder/batch", response_model=MessageResponse)
async def reorder_categories(
    data: CategoryReorder,
    shop = Depends(require_permission("menu_categories", "write")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reorder categories."""
    service = MenuService(db)
    await service.reorder_categories(shop.id, user.id, data.order)
    await db.commit()
    from app.database.redis import invalidate_shop_cache
    await invalidate_shop_cache(shop.id)
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
