"""Customer service."""

import uuid
from typing import Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.customer import Customer
from app.models.membership import CustomerRetailerMembership


class CustomerService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_customer_by_mobile(self, mobile_number: str) -> Optional[Customer]:
        clean = "".join([c for c in mobile_number if c.isdigit()])
        last10 = clean[-10:] if len(clean) >= 10 else clean
        variants = list(set([
            mobile_number.strip(),
            clean,
            f"+91{last10}",
            f"91{last10}",
            last10
        ]))
        stmt = select(Customer).where(Customer.mobile_number.in_(variants))
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def register_customer(self, name: str, mobile_number: str) -> Customer:
        # Check if already exists
        existing = await self.get_customer_by_mobile(mobile_number)
        if existing:
            # If existing customer doesn't have a name set yet, fill it; never overwrite another shop's customer name globally
            if not existing.name and name and name.strip():
                existing.name = name.strip()
                await self.db.commit()
                await self.db.refresh(existing)
            return existing
            
        customer = Customer(name=name.strip() if name else None, mobile_number=mobile_number.strip())
        self.db.add(customer)
        await self.db.commit()
        await self.db.refresh(customer)
        return customer

    async def check_membership(self, customer_id: uuid.UUID, shop_id: uuid.UUID) -> bool:
        membership = await self.get_membership(customer_id, shop_id)
        return membership is not None

    async def get_membership(self, customer_id: uuid.UUID, shop_id: uuid.UUID) -> Optional[CustomerRetailerMembership]:
        stmt = select(CustomerRetailerMembership).where(
            CustomerRetailerMembership.customer_id == customer_id,
            CustomerRetailerMembership.shop_id == shop_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def add_membership(
        self,
        customer_id: uuid.UUID,
        shop_id: uuid.UUID,
        is_retailer_added: bool = False,
        customer_name: Optional[str] = None
    ) -> CustomerRetailerMembership:
        # Check if already a member of this shop
        stmt = select(CustomerRetailerMembership).where(
            CustomerRetailerMembership.customer_id == customer_id,
            CustomerRetailerMembership.shop_id == shop_id
        )
        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()
        
        trimmed_name = customer_name.strip() if customer_name and customer_name.strip() else None

        if existing:
            changed = False
            if is_retailer_added and not existing.is_retailer_added:
                existing.is_retailer_added = True
                changed = True
            if trimmed_name and existing.customer_name != trimmed_name:
                existing.customer_name = trimmed_name
                changed = True
            if changed:
                await self.db.commit()
                await self.db.refresh(existing)
            return existing

        membership = CustomerRetailerMembership(
            customer_id=customer_id,
            shop_id=shop_id,
            is_retailer_added=is_retailer_added,
            customer_name=trimmed_name
        )
        self.db.add(membership)
        await self.db.commit()
        await self.db.refresh(membership)
        return membership
