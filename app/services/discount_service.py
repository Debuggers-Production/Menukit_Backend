"""Discount CRUD service."""

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.discount import Discount
from app.models.shop import Shop
from app.core.exceptions import NotFoundException


class DiscountService:
    """Handles discount CRUD operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_user_shop(self, user_id: uuid.UUID) -> Shop:
        """Get the shop owned by the user."""
        result = await self.db.execute(select(Shop).where(Shop.user_id == user_id))
        shop = result.scalar_one_or_none()
        if not shop:
            raise NotFoundException("Shop not found. Create a shop first.")
        return shop

    async def create_discount(self, user_id: uuid.UUID, data: dict) -> Discount:
        """Create a new discount for the shop."""
        shop = await self._get_user_shop(user_id)
        discount = Discount(shop_id=shop.id, **data)
        self.db.add(discount)
        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(discount)
        return discount

    async def get_discounts(self, shop_id: uuid.UUID) -> List[Discount]:
        """Get all discounts for a shop."""
        result = await self.db.execute(
            select(Discount)
            .where(Discount.shop_id == shop_id)
            .order_by(Discount.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_active_discounts(self, shop_id: uuid.UUID) -> List[Discount]:
        """Get currently active discounts for public display."""
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            select(Discount).where(
                Discount.shop_id == shop_id,
                Discount.is_active == True,
                (Discount.start_date == None) | (Discount.start_date <= now),
                (Discount.end_date == None) | (Discount.end_date >= now),
            )
        )
        return list(result.scalars().all())

    async def update_discount(
        self, user_id: uuid.UUID, discount_id: uuid.UUID, data: dict
    ) -> Discount:
        """Update a discount."""
        shop = await self._get_user_shop(user_id)
        result = await self.db.execute(
            select(Discount).where(
                Discount.id == discount_id,
                Discount.shop_id == shop.id,
            )
        )
        discount = result.scalar_one_or_none()
        if not discount:
            raise NotFoundException("Discount not found")

        for key, value in data.items():
            if value is not None and hasattr(discount, key):
                setattr(discount, key, value)
            elif value is None and key in ("start_date", "end_date", "description", "target_ids", "buy_quantity", "get_quantity", "reward_target_ids", "discount_value"):
                # Allow explicit null clearing for optional fields
                setattr(discount, key, None)

        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(discount)
        return discount

    async def delete_discount(self, user_id: uuid.UUID, discount_id: uuid.UUID):
        """Delete a discount."""
        shop = await self._get_user_shop(user_id)
        result = await self.db.execute(
            select(Discount).where(
                Discount.id == discount_id,
                Discount.shop_id == shop.id,
            )
        )
        discount = result.scalar_one_or_none()
        if not discount:
            raise NotFoundException("Discount not found")
        await self.db.delete(discount)
        await self.db.flush()
        await self.db.commit()

    async def reorder_discounts(self, user_id: uuid.UUID, order_items: List[dict]):
        """Reorder discounts."""
        shop = await self._get_user_shop(user_id)
        
        # Get all discounts for shop to ensure they belong to it
        result = await self.db.execute(
            select(Discount).where(Discount.shop_id == shop.id)
        )
        shop_discounts = {str(d.id): d for d in result.scalars().all()}
        
        for item in order_items:
            # Pydantic v2 support
            item_id = item.id if hasattr(item, "id") else item["id"]
            display_order = item.display_order if hasattr(item, "display_order") else item["display_order"]
            
            if item_id in shop_discounts:
                shop_discounts[item_id].display_order = display_order
                
        await self.db.flush()
        await self.db.commit()
