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
        stmt = select(Customer).where(Customer.mobile_number == mobile_number)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def register_customer(self, name: str, mobile_number: str) -> Customer:
        # Check if already exists
        existing = await self.get_customer_by_mobile(mobile_number)
        if existing:
            # Update name if provided? Just return existing for now
            return existing
            
        customer = Customer(name=name, mobile_number=mobile_number)
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

    async def add_membership(self, customer_id: uuid.UUID, shop_id: uuid.UUID, is_retailer_added: bool = False) -> CustomerRetailerMembership:
        # Check if already a member
        stmt = select(CustomerRetailerMembership).where(
            CustomerRetailerMembership.customer_id == customer_id,
            CustomerRetailerMembership.shop_id == shop_id
        )
        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            if is_retailer_added and not existing.is_retailer_added:
                existing.is_retailer_added = True
                await self.db.commit()
                await self.db.refresh(existing)
            return existing

        membership = CustomerRetailerMembership(
            customer_id=customer_id,
            shop_id=shop_id,
            is_retailer_added=is_retailer_added
        )
        self.db.add(membership)
        await self.db.commit()
        await self.db.refresh(membership)
        return membership
