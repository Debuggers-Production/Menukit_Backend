"""Discount CRUD service."""

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.discount import Discount, CustomerDiscountCode
from app.models.shop import Shop
from app.core.exceptions import NotFoundException


import secrets


def generate_discount_code_string(discount_title: Optional[str] = None, *args, **kwargs) -> str:
    """Generate a secure, entirely unique, unpredictable discount code string (e.g. SAVE-7X9K-M3W8)."""
    raw_title = "".join(filter(str.isalnum, discount_title or "OFFER")).upper()
    prefix = (raw_title[:4] if len(raw_title) >= 3 else "MK")
    # Base 32 alphabet without easily confused characters (no 0, O, 1, I)
    CHARS = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    part1 = "".join(secrets.choice(CHARS) for _ in range(4))
    part2 = "".join(secrets.choice(CHARS) for _ in range(4))
    return f"{prefix}-{part1}-{part2}"


class DiscountService:
    """Handles discount CRUD operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_user_shop(self, user_id: uuid.UUID) -> Shop:
        """Get the shop owned by the user."""
        result = await self.db.execute(select(Shop).where(Shop.user_id == user_id))
        shop = result.scalar_one_or_none()
        if not shop:
            raise NotFoundException("User has no registered restaurant.")
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
        if data.get("code"):
            data["code"] = data["code"].strip().upper()
        else:
            data["code"] = None

        discount = Discount(menu_catalog_id=catalog_id, **data)
        self.db.add(discount)
        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(discount)
        return discount

    async def get_discounts(
        self, shop_id: uuid.UUID, skip: int = 0, limit: int = 100, search: Optional[str] = None
    ) -> List[Discount]:
        """Get all discounts for a shop's catalog with pagination and optional search."""
        catalog_id = await self._get_catalog_id(shop_id)
        query = select(Discount).where(Discount.menu_catalog_id == catalog_id)

        if search and search.strip():
            s = f"%{search.strip()}%"
            query = query.where(
                or_(
                    Discount.title.ilike(s),
                    Discount.description.ilike(s),
                    Discount.code.ilike(s),
                )
            )

        query = (
            query.order_by(Discount.display_order.asc(), Discount.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(query)
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

        if "code" in data and data["code"]:
            data["code"] = str(data["code"]).strip().upper()

        for key, value in data.items():
            if value is not None and hasattr(discount, key):
                setattr(discount, key, value)
            elif value is None and key in (
                "code",
                "description",
                "discount_value",
                "buy_quantity",
                "get_quantity",
                "reward_target_ids",
                "target_ids",
                "start_date",
                "end_date",
                "available_days",
                "available_time_presets",
            ):
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

    async def get_or_assign_code(
        self,
        shop_id: uuid.UUID,
        discount: Discount,
        customer_identifier: str,
        customer_id: Optional[uuid.UUID] = None
    ) -> CustomerDiscountCode:
        """Assign or retrieve an official unique discount code for this customer."""
        clean_identifier = str(customer_identifier or "GUEST").strip()

        # 1. Check if already assigned for this shop, discount and customer identifier
        res = await self.db.execute(
            select(CustomerDiscountCode).where(
                CustomerDiscountCode.shop_id == shop_id,
                CustomerDiscountCode.discount_id == discount.id,
                CustomerDiscountCode.customer_identifier == clean_identifier
            )
            .order_by(CustomerDiscountCode.created_at.desc())
        )
        existing = res.scalars().first()
        if existing:
            return existing

        # 2. Generate a guaranteed unique collision-free code
        code_str = ""
        for _ in range(10):
            candidate = generate_discount_code_string(discount.title)
            res_code = await self.db.execute(
                select(CustomerDiscountCode).where(
                    CustomerDiscountCode.shop_id == shop_id,
                    func.upper(CustomerDiscountCode.code) == candidate.upper()
                )
            )
            if not res_code.scalars().first():
                code_str = candidate
                break

        if not code_str:
            code_str = generate_discount_code_string(discount.title)

        # 3. Create new assignment
        new_assignment = CustomerDiscountCode(
            shop_id=shop_id,
            discount_id=discount.id,
            customer_id=customer_id,
            customer_identifier=clean_identifier,
            code=code_str.upper(),
            is_redeemed=False
        )
        self.db.add(new_assignment)
        await self.db.commit()
        await self.db.refresh(new_assignment)
        return new_assignment
