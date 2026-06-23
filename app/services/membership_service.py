"""Membership service."""

import uuid
from typing import List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.customer import Customer
from app.models.membership import CustomerRetailerMembership
from app.models.analytics import MembershipEvent
from app.services.customer_service import CustomerService


class MembershipService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.customer_service = CustomerService(db)

    async def add_member(self, shop_id: uuid.UUID, name: str, mobile_number: str) -> CustomerRetailerMembership:
        # Upsert global customer
        customer = await self.customer_service.register_customer(name, mobile_number)
        # Create membership
        return await self.customer_service.add_membership(customer.id, shop_id, is_retailer_added=True)

    async def update_member(self, shop_id: uuid.UUID, customer_id: uuid.UUID, name: str, mobile_number: str) -> None:
        stmt = select(CustomerRetailerMembership).where(
            CustomerRetailerMembership.shop_id == shop_id,
            CustomerRetailerMembership.customer_id == customer_id
        )
        res = await self.db.execute(stmt)
        membership = res.scalar_one_or_none()
        if not membership:
            raise ValueError("Membership not found")

        stmt_cust = select(Customer).where(Customer.id == customer_id)
        res_cust = await self.db.execute(stmt_cust)
        customer = res_cust.scalar_one()

        customer.name = name
        customer.mobile_number = mobile_number
        await self.db.commit()

    async def remove_member(self, shop_id: uuid.UUID, customer_id: uuid.UUID) -> None:
        stmt = select(CustomerRetailerMembership).where(
            CustomerRetailerMembership.shop_id == shop_id,
            CustomerRetailerMembership.customer_id == customer_id
        )
        res = await self.db.execute(stmt)
        membership = res.scalar_one_or_none()
        if not membership:
            raise ValueError("Membership not found")
        
        await self.db.delete(membership)
        await self.db.commit()

    async def get_analytics(self, shop_id: uuid.UUID) -> Dict[str, Any]:
        stmt_total = select(func.count(CustomerRetailerMembership.id)).where(
            CustomerRetailerMembership.shop_id == shop_id
        )
        res_total = await self.db.execute(stmt_total)
        total_members = res_total.scalar() or 0

        stmt_manual = select(func.count(CustomerRetailerMembership.id)).where(
            CustomerRetailerMembership.shop_id == shop_id,
            CustomerRetailerMembership.is_retailer_added == True
        )
        res_manual = await self.db.execute(stmt_manual)
        manually_added = res_manual.scalar() or 0

        auto_registered = max(0, total_members - manually_added)

        return {
            "total_members": total_members,
            "manually_added": manually_added,
            "auto_registered": auto_registered
        }

    async def log_event(self, shop_id: uuid.UUID, event_type: str, customer_id: uuid.UUID | None = None):
        event = MembershipEvent(
            shop_id=shop_id,
            event_type=event_type,
            customer_id=customer_id
        )
        self.db.add(event)
        await self.db.commit()

    async def get_repeated_customers(self, shop_id: uuid.UUID, min_visits: int = 2) -> List[Dict[str, Any]]:
        stmt = (
            select(
                Customer.id,
                Customer.name,
                Customer.mobile_number,
                func.min(CustomerRetailerMembership.created_at).label("joined_at"),
                func.count(func.distinct(func.date(MembershipEvent.event_time))).label("visit_count")
            )
            .join(MembershipEvent, MembershipEvent.customer_id == Customer.id)
            .join(
                CustomerRetailerMembership,
                (CustomerRetailerMembership.customer_id == Customer.id) &
                (CustomerRetailerMembership.shop_id == shop_id)
            )
            .where(
                MembershipEvent.shop_id == shop_id,
                MembershipEvent.event_type.in_(["member_matched", "otp_verified", "token_verified", "discount_unlocked"])
            )
            .group_by(Customer.id, Customer.name, Customer.mobile_number)
            .having(func.count(func.distinct(func.date(MembershipEvent.event_time))) >= min_visits)
            .order_by(func.count(func.distinct(func.date(MembershipEvent.event_time))).desc())
        )
        
        result = await self.db.execute(stmt)
        rows = result.all()
        
        return [
            {
                "id": row.id,
                "name": row.name,
                "mobile_number": row.mobile_number,
                "joined_at": row.joined_at,
                "visit_count": row.visit_count
            }
            for row in rows
        ]
