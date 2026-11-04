"""Membership service."""

import uuid
from typing import List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text

from app.models.customer import Customer
from app.models.membership import CustomerRetailerMembership
from app.models.analytics import MembershipEvent
from app.services.customer_service import CustomerService


class MembershipService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.customer_service = CustomerService(db)

    async def add_member(self, shop_id: uuid.UUID, name: str, mobile_number: str) -> CustomerRetailerMembership:
        clean = "".join([c for c in mobile_number if c.isdigit()])
        last10 = clean[-10:] if len(clean) >= 10 else clean
        variants = list(set([
            mobile_number.strip(),
            clean,
            f"+{clean}",
            f"+91{last10}",
            f"91{last10}",
            last10
        ]))

        # Check if ANY existing customer matching this mobile number is ALREADY a member of this shop
        cust_stmt = select(Customer.id).where(Customer.mobile_number.in_(variants))
        cust_res = await self.db.execute(cust_stmt)
        matched_customer_ids = list(cust_res.scalars().all())

        if matched_customer_ids:
            mem_stmt = select(CustomerRetailerMembership).where(
                CustomerRetailerMembership.shop_id == shop_id,
                CustomerRetailerMembership.customer_id.in_(matched_customer_ids)
            )
            mem_res = await self.db.execute(mem_stmt)
            existing_mem = mem_res.scalar_one_or_none()
            if existing_mem:
                raise ValueError("This mobile number is already registered as a member in your shop.")

        # Upsert global customer
        customer = await self.customer_service.register_customer(name, mobile_number)
        # Create shop-specific membership with customer_name
        return await self.customer_service.add_membership(customer.id, shop_id, is_retailer_added=True, customer_name=name)

    async def update_member(self, shop_id: uuid.UUID, customer_id: uuid.UUID, name: str, mobile_number: str) -> None:
        raise ValueError("Member editing is disabled")

    async def remove_member(self, shop_id: uuid.UUID, customer_id: uuid.UUID) -> None:
        raise ValueError("Member deletion is disabled")

    async def get_analytics(self, shop_id: uuid.UUID) -> Dict[str, Any]:
        stmt_total = select(func.count(CustomerRetailerMembership.id)).where(
            CustomerRetailerMembership.shop_id == shop_id
        )
        res_total = await self.db.execute(stmt_total)
        total_members = res_total.scalar_one()

        stmt_manual = select(func.count(CustomerRetailerMembership.id)).where(
            CustomerRetailerMembership.shop_id == shop_id,
            CustomerRetailerMembership.is_retailer_added == True
        )
        res_manual = await self.db.execute(stmt_manual)
        manually_added = res_manual.scalar_one()

        auto_registered = total_members - manually_added

        # Count repeated customers
        repeated_list = await self.get_repeated_customers(shop_id, min_visits=2)
        repeated_count = len(repeated_list)

        return {
            "total_members": total_members,
            "manually_added": manually_added,
            "auto_registered": auto_registered,
            "repeated_count": repeated_count
        }

    async def delete_all_members(self, shop_id: uuid.UUID, delete_type: str = "all") -> int:
        """
        Delete memberships for a shop.
        delete_type:
            - 'existing' : only manually added (is_retailer_added == True)
            - 'new'      : only auto-registered (is_retailer_added == False)
            - 'all'      : both types
        """
        stmt = select(CustomerRetailerMembership).where(
            CustomerRetailerMembership.shop_id == shop_id
        )
        if delete_type == "existing":
            stmt = stmt.where(CustomerRetailerMembership.is_retailer_added == True)
        elif delete_type == "new":
            stmt = stmt.where(CustomerRetailerMembership.is_retailer_added == False)

        res = await self.db.execute(stmt)
        memberships = res.scalars().all()
        count = len(memberships)

        for m in memberships:
            await self.db.delete(m)

        await self.db.commit()
        return count

    async def get_members(self, shop_id: uuid.UUID) -> List[CustomerRetailerMembership]:
        stmt = select(CustomerRetailerMembership).where(
            CustomerRetailerMembership.shop_id == shop_id
        ).order_by(CustomerRetailerMembership.created_at.desc())
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def log_event(self, shop_id: uuid.UUID, event_type: str, customer_id: uuid.UUID = None) -> None:
        event = MembershipEvent(
            shop_id=shop_id,
            event_type=event_type,
            customer_id=customer_id
        )
        self.db.add(event)
        await self.db.commit()

    async def get_repeated_customers(self, shop_id: uuid.UUID, min_visits: int = 2) -> List[Dict[str, Any]]:
        stmt = text("""
            WITH order_visits AS (
                SELECT 
                    RIGHT(REGEXP_REPLACE(customer_phone, '[^0-9]', '', 'g'), 10) as clean_phone,
                    DATE(created_at) as visit_date
                FROM orders
                WHERE shop_id = :sid 
                  AND UPPER(order_status) NOT IN ('CANCELLED', 'REJECTED')
                  AND customer_phone IS NOT NULL AND customer_phone != ''
            ),
            event_visits AS (
                SELECT 
                    RIGHT(REGEXP_REPLACE(c.mobile_number, '[^0-9]', '', 'g'), 10) as clean_phone,
                    DATE(me.event_time) as visit_date
                FROM membership_events me
                JOIN customers c ON c.id = me.customer_id
                WHERE me.shop_id = :sid
            ),
            all_visits AS (
                SELECT clean_phone, visit_date FROM order_visits
                UNION
                SELECT clean_phone, visit_date FROM event_visits
            )
            SELECT 
                c.id,
                COALESCE(m.customer_name, c.name) as name,
                c.mobile_number,
                MIN(m.created_at) as joined_at,
                GREATEST(COUNT(DISTINCT av.visit_date), COUNT(DISTINCT o.id), 1) as visit_count
            FROM customers c
            JOIN customer_retailer_memberships m ON m.customer_id = c.id AND m.shop_id = :sid
            LEFT JOIN all_visits av ON av.clean_phone = RIGHT(REGEXP_REPLACE(c.mobile_number, '[^0-9]', '', 'g'), 10)
            LEFT JOIN orders o ON RIGHT(REGEXP_REPLACE(o.customer_phone, '[^0-9]', '', 'g'), 10) = RIGHT(REGEXP_REPLACE(c.mobile_number, '[^0-9]', '', 'g'), 10) 
                              AND o.shop_id = :sid 
                              AND UPPER(o.order_status) NOT IN ('CANCELLED', 'REJECTED')
            GROUP BY c.id, c.name, c.mobile_number, m.customer_name
            HAVING COUNT(DISTINCT av.visit_date) >= :min_visits OR COUNT(DISTINCT o.id) >= :min_visits
            ORDER BY GREATEST(COUNT(DISTINCT av.visit_date), COUNT(DISTINCT o.id)) DESC, MIN(m.created_at) DESC
        """)
        
        result = await self.db.execute(stmt, {"sid": shop_id, "min_visits": min_visits})
        rows = result.fetchall()
        
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
