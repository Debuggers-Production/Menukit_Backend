"""Discount management API endpoints."""

import uuid
from typing import List

from fastapi import APIRouter, Depends,Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.core.deps import get_current_user, require_permission
from app.schemas.discount import DiscountCreate, DiscountUpdate, DiscountResponse, DiscountReorder
from app.schemas.common import MessageResponse
from app.services.discount_service import DiscountService
from app.services.shop_service import ShopService
from app.models.user import User

router = APIRouter(prefix="/discounts", tags=["Discounts"])


def _discount_response(d) -> DiscountResponse:
    """Convert Discount model to response."""
    return DiscountResponse(
        id=str(d.id),
        shop_id=str(d.menu_catalog_id),  # expose catalog_id as shop_id for frontend compat
        title=d.title,
        description=d.description,
        discount_type=d.discount_type,
        discount_value=str(d.discount_value) if d.discount_value is not None else None,
        buy_quantity=d.buy_quantity,
        get_quantity=d.get_quantity,
        reward_target_ids=d.reward_target_ids,
        applies_to=d.applies_to,
        target_ids=d.target_ids,
        start_date=d.start_date.isoformat() if d.start_date else None,
        end_date=d.end_date.isoformat() if d.end_date else None,
        available_days=d.available_days,
        available_time_presets=d.available_time_presets,
        is_active=d.is_active,
        visibility_type=d.visibility_type,
        display_order=d.display_order,
        created_at=str(d.created_at),
        updated_at=str(d.updated_at),
    )


@router.post("", response_model=DiscountResponse)
async def create_discount(
    data: DiscountCreate,
    shop = Depends(require_permission("discounts", "write")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new discount."""
    service = DiscountService(db)
    discount = await service.create_discount(shop.id, user.id, data.model_dump())
    return _discount_response(discount)


@router.get("", response_model=List[DiscountResponse])
async def get_discounts(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    shop = Depends(require_permission("discounts", "read")),
    db: AsyncSession = Depends(get_db),
):
    """Get all discounts for the user's shop with pagination."""
    service = DiscountService(db)
    discounts = await service.get_discounts(shop.id, skip=skip, limit=limit)
    return [_discount_response(d) for d in discounts]


@router.put("/{discount_id}", response_model=DiscountResponse)
async def update_discount(
    discount_id: str,
    data: DiscountUpdate,
    shop = Depends(require_permission("discounts", "write")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a discount."""
    service = DiscountService(db)
    discount = await service.update_discount(
        shop.id, user.id, uuid.UUID(discount_id), data.model_dump(exclude_unset=True)
    )
    return _discount_response(discount)


@router.put("/reorder/batch", response_model=MessageResponse)
@router.post("/reorder", response_model=MessageResponse)
async def reorder_discounts(
    data: DiscountReorder,
    shop = Depends(require_permission("discounts", "write")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reorder discounts."""
    service = DiscountService(db)
    order_list = [
        {
            "id": item["id"] if isinstance(item, dict) else getattr(item, "id"),
            "display_order": item["display_order"] if isinstance(item, dict) else getattr(item, "display_order")
        }
        for item in data.order
    ]
    await service.reorder_discounts(shop.id, user.id, order_list)
    await db.commit()
    from app.database.redis import invalidate_shop_cache
    await invalidate_shop_cache(shop.id)
    return MessageResponse(message="Discounts reordered successfully")


@router.delete("/all", response_model=MessageResponse)
async def delete_all_discounts(
    shop = Depends(require_permission("discounts", "write")),
    db: AsyncSession = Depends(get_db),
):
    """Delete all discounts for the user's shop's catalog."""
    service = DiscountService(db)
    discounts = await service.get_discounts(shop.id)
    
    for discount in discounts:
        await db.delete(discount)
        
    await db.commit()
    return MessageResponse(message=f"Deleted {len(discounts)} discounts successfully")


@router.delete("/{discount_id}", response_model=MessageResponse)
async def delete_discount(
    discount_id: str,
    shop = Depends(require_permission("discounts", "write")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a discount."""
    service = DiscountService(db)
    await service.delete_discount(shop.id, user.id, uuid.UUID(discount_id))
    return MessageResponse(message="Discount deleted successfully")
