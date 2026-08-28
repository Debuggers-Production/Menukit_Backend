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

    async def _get_catalog_id(self, shop_id: uuid.UUID) -> uuid.UUID:
        """Resolve the menu_catalog_id for a given shop."""
        result = await self.db.execute(
            select(Shop.menu_catalog_id).where(Shop.id == shop_id)
        )
        catalog_id = result.scalar_one_or_none()
        if not catalog_id:
            raise NotFoundException("This shop has no linked menu catalog.")
        return catalog_id

    async def create_discount(self, shop_id: uuid.UUID, user_id: uuid.UUID, data: dict) -> Discount:
        """Create a new discount for the shop's catalog."""
        catalog_id = await self._get_catalog_id(shop_id)
        discount = Discount(menu_catalog_id=catalog_id, **data)
        self.db.add(discount)
        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(discount)
        return discount

    async def get_discounts(self, shop_id: uuid.UUID, skip: int = 0, limit: int = 100) -> List[Discount]:
        """Get all discounts for a shop's catalog with pagination."""
        catalog_id = await self._get_catalog_id(shop_id)
        result = await self.db.execute(
            select(Discount)
            .where(Discount.menu_catalog_id == catalog_id)
            .order_by(Discount.display_order.asc(), Discount.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_active_discounts(self, shop_id: uuid.UUID) -> List[Discount]:
        """Get currently active discounts for public display."""
        catalog_id = await self._get_catalog_id(shop_id)
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            select(Discount).where(
                Discount.menu_catalog_id == catalog_id,
                Discount.is_active == True,
                (Discount.start_date == None) | (Discount.start_date <= now),
                (Discount.end_date == None) | (Discount.end_date >= now),
            )
            .order_by(Discount.display_order.asc(), Discount.created_at.desc())
        )
        return list(result.scalars().all())

    async def update_discount(
        self, shop_id: uuid.UUID, user_id: uuid.UUID, discount_id: uuid.UUID, data: dict
    ) -> Discount:
        """Update a discount."""
        catalog_id = await self._get_catalog_id(shop_id)
        result = await self.db.execute(
            select(Discount).where(Discount.id == discount_id, Discount.menu_catalog_id == catalog_id)
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

    async def delete_discount(self, shop_id: uuid.UUID, user_id: uuid.UUID, discount_id: uuid.UUID):
        """Delete a discount."""
        catalog_id = await self._get_catalog_id(shop_id)
        result = await self.db.execute(
            select(Discount).where(Discount.id == discount_id, Discount.menu_catalog_id == catalog_id)
        )
        discount = result.scalar_one_or_none()
        if not discount:
            raise NotFoundException("Discount not found")
        await self.db.delete(discount)
        await self.db.flush()
        await self.db.commit()

    async def reorder_discounts(self, shop_id: uuid.UUID, user_id: uuid.UUID, order_items: List[dict]):
        """Reorder discounts."""
        catalog_id = await self._get_catalog_id(shop_id)
        
        # Get all discounts for catalog to ensure they belong to it
        result = await self.db.execute(
            select(Discount).where(Discount.menu_catalog_id == catalog_id)
        )
        catalog_discounts = {str(d.id): d for d in result.scalars().all()}
        
        for item in order_items:
            # Pydantic v2 / dict support
            item_id = str(item.id if hasattr(item, "id") else item["id"])
            display_order = item.display_order if hasattr(item, "display_order") else item["display_order"]
            
            if item_id in catalog_discounts:
                catalog_discounts[item_id].display_order = int(display_order)
                
        await self.db.flush()
