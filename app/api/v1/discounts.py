"""Discount management API endpoints."""

import uuid
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.core.deps import get_current_user
from app.schemas.discount import DiscountCreate, DiscountUpdate, DiscountResponse
from app.schemas.common import MessageResponse
from app.services.discount_service import DiscountService
from app.services.shop_service import ShopService
from app.models.user import User

router = APIRouter(prefix="/discounts", tags=["Discounts"])


def _discount_response(d) -> DiscountResponse:
    """Convert Discount model to response."""
    return DiscountResponse(
        id=str(d.id),
        shop_id=str(d.shop_id),
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
        created_at=str(d.created_at),
        updated_at=str(d.updated_at),
    )


@router.post("", response_model=DiscountResponse)
async def create_discount(
    data: DiscountCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new discount."""
    service = DiscountService(db)
    discount = await service.create_discount(user.id, data.model_dump())
    return _discount_response(discount)


@router.get("", response_model=List[DiscountResponse])
async def get_discounts(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all discounts for the shop."""
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_user(user.id)
    if not shop:
        return []
    service = DiscountService(db)
    discounts = await service.get_discounts(shop.id)
    return [_discount_response(d) for d in discounts]


@router.put("/{discount_id}", response_model=DiscountResponse)
async def update_discount(
    discount_id: str,
    data: DiscountUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a discount."""
    service = DiscountService(db)
    discount = await service.update_discount(
        user.id, uuid.UUID(discount_id), data.model_dump(exclude_unset=True)
    )
    return _discount_response(discount)


@router.delete("/{discount_id}", response_model=MessageResponse)
async def delete_discount(
    discount_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a discount."""
    service = DiscountService(db)
    await service.delete_discount(user.id, uuid.UUID(discount_id))
    return MessageResponse(message="Discount deleted successfully")
