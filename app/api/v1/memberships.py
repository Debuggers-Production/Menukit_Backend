import uuid
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, text
from sqlalchemy.orm import joinedload


from app.database.session import get_db
from app.core.deps import get_current_user, require_permission
from app.models.user import User
from app.models.customer import Customer
from app.models.membership import CustomerRetailerMembership
from app.models.analytics import MembershipEvent
from app.schemas.membership import (
    AddMemberRequest, MembershipAnalyticsResponse, MembershipEventRequest, MemberResponse,
    RepeatedCustomerResponse
)
from app.services.membership_service import MembershipService
from app.services.shop_service import ShopService

router = APIRouter(prefix="/memberships", tags=["Memberships"])


class MemberItemSchema(BaseModel):
    id: uuid.UUID
    name: Optional[str] = None
    mobile_number: str
    joined_at: datetime
    is_retailer_added: bool = True
    visit_count: Optional[int] = None


class PaginatedMembersListResponse(BaseModel):
    total_count: int
    has_more: bool
    skip: int
    limit: int
    tab: str
    items: List[MemberItemSchema]


async def check_memberships_subscription(shop_id: uuid.UUID, db: AsyncSession, require_details: bool = False):
    """Backend subscription verification for membership data endpoints."""
    from app.services.subscription_helper import get_shop_subscription_permissions
    perms = await get_shop_subscription_permissions(shop_id, db)
    if perms["is_expired"]:
        raise HTTPException(
            status_code=403,
            detail="Subscription required: Member data features are locked due to an expired subscription. Please renew your plan."
        )
    
    if require_details:
        if not perms["member_details"]:
            raise HTTPException(
                status_code=403,
                detail="Feature 'member-details' (New Member + Details) is required to view individual customer details. Please upgrade your plan."
            )
    else:
        if not (perms["member_count"] or perms["member_details"]):
            raise HTTPException(
                status_code=403,
                detail="Subscription required: At least 'New Member Count' or 'New Member + Details' module is required to access member features."
            )


@router.post("/retailer/{shop_id}/add")
async def add_member(
    shop_id: uuid.UUID,
    data: AddMemberRequest,
    shop = Depends(require_permission("analytics", "write")),
    db: AsyncSession = Depends(get_db)
):
    """Retailer adds a member directly to their shop."""
    if shop.id != shop_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this shop")

    await check_memberships_subscription(shop_id, db, require_details=True)

    membership_service = MembershipService(db)
    membership = await membership_service.add_member(shop_id, data.name, data.mobile_number)
    
    return {"message": "Member added successfully", "customer_id": membership.customer_id}


@router.get("/retailer/{shop_id}/analytics", response_model=MembershipAnalyticsResponse)
async def get_membership_analytics(
    shop_id: uuid.UUID,
    shop = Depends(require_permission("analytics", "read")),
    db: AsyncSession = Depends(get_db)
):
    """Get aggregate membership analytics for retailer dashboard."""
    if shop.id != shop_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this shop")

    await check_memberships_subscription(shop_id, db, require_details=False)

    membership_service = MembershipService(db)
    analytics = await membership_service.get_analytics(shop_id)
    return analytics


@router.post("/events")
async def log_membership_event(
    data: MembershipEventRequest,
    shop_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    """Log customer events for analytics (e.g. from popup)."""
    membership_service = MembershipService(db)
    await membership_service.log_event(shop_id, data.event_type, data.customer_id)
    return {"status": "ok"}

@router.get("/retailer/{shop_id}/members", response_model=List[MemberResponse])
async def get_retailer_members(
    shop_id: uuid.UUID,
    shop = Depends(require_permission("analytics", "read")),
    db: AsyncSession = Depends(get_db)
):
    """Get list of manually added members for retailer dashboard."""
    if shop.id != shop_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this shop")

    await check_memberships_subscription(shop_id, db, require_details=True)

    stmt = select(CustomerRetailerMembership).options(
        joinedload(CustomerRetailerMembership.customer)
    ).where(
        CustomerRetailerMembership.shop_id == shop_id,
        CustomerRetailerMembership.is_retailer_added == True
    ).order_by(CustomerRetailerMembership.created_at.desc())

    result = await db.execute(stmt)
    memberships = result.scalars().all()

    return [
        MemberResponse(
            id=m.customer.id,
            name=m.customer.name,
            mobile_number=m.customer.mobile_number,
            joined_at=m.created_at
        )
        for m in memberships
    ]


@router.get("/retailer/{shop_id}/auto-registered", response_model=List[MemberResponse])
async def get_auto_registered_members(
    shop_id: uuid.UUID,
    shop = Depends(require_permission("analytics", "read")),
    db: AsyncSession = Depends(get_db)
):
    """Get list of auto-registered members for retailer dashboard."""
    if shop.id != shop_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this shop")

    await check_memberships_subscription(shop_id, db, require_details=True)

    stmt = select(CustomerRetailerMembership).options(
        joinedload(CustomerRetailerMembership.customer)
    ).where(
        CustomerRetailerMembership.shop_id == shop_id,
        CustomerRetailerMembership.is_retailer_added == False
    ).order_by(CustomerRetailerMembership.created_at.desc())

    result = await db.execute(stmt)
    memberships = result.scalars().all()

    return [
        MemberResponse(
            id=m.customer.id,
            name=m.customer.name,
            mobile_number=m.customer.mobile_number,
            joined_at=m.created_at
        )
        for m in memberships
    ]


@router.get("/retailer/{shop_id}/repeated", response_model=List[RepeatedCustomerResponse])
async def get_repeated_customers(
    shop_id: uuid.UUID,
    min_visits: int = 2,
    shop = Depends(require_permission("analytics", "read")),
    db: AsyncSession = Depends(get_db)
):
    """Get list of customers with multiple visits."""
    if shop.id != shop_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this shop")

    await check_memberships_subscription(shop_id, db, require_details=True)

    membership_service = MembershipService(db)
    customers = await membership_service.get_repeated_customers(shop_id, min_visits)

    return [RepeatedCustomerResponse(**c) for c in customers]


@router.get("/retailer/{shop_id}/members-list", response_model=PaginatedMembersListResponse)
async def get_paginated_members(
    shop_id: uuid.UUID,
    tab: str = Query("existing"),  # existing, new, repeated
    search: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    min_visits: int = Query(2, ge=2),
    shop = Depends(require_permission("analytics", "read")),
    db: AsyncSession = Depends(get_db)
):
    """Get paginated member list by tab (existing, new, repeated) with backend SQL search."""
    if shop.id != shop_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this shop")

    await check_memberships_subscription(shop_id, db, require_details=True)

    items = []
    total_count = 0

    if tab == "repeated":
        repeated_query_str = """
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
                c.name,
                c.mobile_number,
                MIN(m.created_at) as joined_at,
                m.is_retailer_added,
                GREATEST(COUNT(DISTINCT av.visit_date), COUNT(DISTINCT o.id), 1) as visit_count
            FROM customers c
            JOIN customer_retailer_memberships m ON m.customer_id = c.id AND m.shop_id = :sid
            LEFT JOIN all_visits av ON av.clean_phone = RIGHT(REGEXP_REPLACE(c.mobile_number, '[^0-9]', '', 'g'), 10)
            LEFT JOIN orders o ON RIGHT(REGEXP_REPLACE(o.customer_phone, '[^0-9]', '', 'g'), 10) = RIGHT(REGEXP_REPLACE(c.mobile_number, '[^0-9]', '', 'g'), 10) 
                              AND o.shop_id = :sid 
                              AND UPPER(o.order_status) NOT IN ('CANCELLED', 'REJECTED')
        """
        params = {"sid": shop_id, "min_visits": min_visits}
        if search and search.strip():
            repeated_query_str += " WHERE (c.name ILIKE :search OR c.mobile_number ILIKE :search)"
            params["search"] = f"%{search.strip()}%"

        repeated_query_str += """
            GROUP BY c.id, c.name, c.mobile_number, m.is_retailer_added
            HAVING COUNT(DISTINCT av.visit_date) >= :min_visits OR COUNT(DISTINCT o.id) >= :min_visits
            ORDER BY GREATEST(COUNT(DISTINCT av.visit_date), COUNT(DISTINCT o.id)) DESC, MIN(m.created_at) DESC
        """

        result = await db.execute(text(repeated_query_str), params)
        all_rows = result.fetchall()
        total_count = len(all_rows)
        paginated_rows = all_rows[skip : skip + limit]

        for r in paginated_rows:
            items.append(MemberItemSchema(
                id=r.id,
                name=r.name,
                mobile_number=r.mobile_number,
                joined_at=r.joined_at,
                is_retailer_added=r.is_retailer_added,
                visit_count=r.visit_count
            ))

    else:
        is_retailer_added = (tab == "existing")
        members_query_str = """
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
                c.name,
                c.mobile_number,
                MIN(m.created_at) as joined_at,
                m.is_retailer_added,
                GREATEST(COUNT(DISTINCT av.visit_date), COUNT(DISTINCT o.id), 1) as visit_count
            FROM customers c
            JOIN customer_retailer_memberships m ON m.customer_id = c.id AND m.shop_id = :sid
            LEFT JOIN all_visits av ON av.clean_phone = RIGHT(REGEXP_REPLACE(c.mobile_number, '[^0-9]', '', 'g'), 10)
            LEFT JOIN orders o ON RIGHT(REGEXP_REPLACE(o.customer_phone, '[^0-9]', '', 'g'), 10) = RIGHT(REGEXP_REPLACE(c.mobile_number, '[^0-9]', '', 'g'), 10) 
                              AND o.shop_id = :sid 
                              AND UPPER(o.order_status) NOT IN ('CANCELLED', 'REJECTED')
            WHERE m.is_retailer_added = :is_ret
        """
        params = {"sid": shop_id, "is_ret": is_retailer_added}
        if search and search.strip():
            members_query_str += " AND (c.name ILIKE :search OR c.mobile_number ILIKE :search)"
            params["search"] = f"%{search.strip()}%"

        members_query_str += """
            GROUP BY c.id, c.name, c.mobile_number, m.is_retailer_added
            ORDER BY MIN(m.created_at) DESC
        """

        result = await db.execute(text(members_query_str), params)
        all_rows = result.fetchall()
        total_count = len(all_rows)
        paginated_rows = all_rows[skip : skip + limit]

        for r in paginated_rows:
            items.append(MemberItemSchema(
                id=r.id,
                name=r.name,
                mobile_number=r.mobile_number,
                joined_at=r.joined_at,
                is_retailer_added=r.is_retailer_added,
                visit_count=r.visit_count
            ))

    has_more = (skip + len(items)) < total_count

    return PaginatedMembersListResponse(
        total_count=total_count,
        has_more=has_more,
        skip=skip,
        limit=limit,
        tab=tab,
        items=items
    )



class BatchConvertMembersRequest(BaseModel):
    customer_ids: Optional[List[uuid.UUID]] = None



@router.post("/retailer/{shop_id}/members/batch-convert")
async def batch_convert_to_members(
    shop_id: uuid.UUID,
    data: Optional[BatchConvertMembersRequest] = None,
    shop = Depends(require_permission("analytics", "write")),
    db: AsyncSession = Depends(get_db)
):
    """Convert multiple or all auto-registered members to manually verified members."""
    if shop.id != shop_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this shop")

    conditions = [
        CustomerRetailerMembership.shop_id == shop_id,
        CustomerRetailerMembership.is_retailer_added == False
    ]
    if data and data.customer_ids and len(data.customer_ids) > 0:
        conditions.append(CustomerRetailerMembership.customer_id.in_(data.customer_ids))

    stmt = select(CustomerRetailerMembership).where(*conditions)
    result = await db.execute(stmt)
    memberships = result.scalars().all()

    if not memberships:
        return {"message": "No unverified customers found to convert", "converted_count": 0}

    for m in memberships:
        m.is_retailer_added = True

    await db.commit()
    return {"message": f"Successfully verified and added {len(memberships)} customer(s)", "converted_count": len(memberships)}



@router.post("/retailer/{shop_id}/members/{customer_id}/convert")
async def convert_to_member(
    shop_id: uuid.UUID,
    customer_id: uuid.UUID,
    shop = Depends(require_permission("analytics", "write")),
    db: AsyncSession = Depends(get_db)
):
    """Convert an auto-registered member to a manually verified member."""
    if shop.id != shop_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this shop")

    stmt = select(CustomerRetailerMembership).where(
        CustomerRetailerMembership.shop_id == shop_id,
        CustomerRetailerMembership.customer_id == customer_id,
        CustomerRetailerMembership.is_retailer_added == False
    )
    result = await db.execute(stmt)
    membership = result.scalar_one_or_none()

    if not membership:
        raise HTTPException(status_code=404, detail="Auto-registered membership not found")

    membership.is_retailer_added = True
    await db.commit()

    return {"message": "Customer converted to verified member successfully"}


@router.put("/retailer/{shop_id}/members/{customer_id}")
async def update_member(
    shop_id: uuid.UUID,
    customer_id: uuid.UUID,
    data: AddMemberRequest,
    shop = Depends(require_permission("analytics", "write")),
    db: AsyncSession = Depends(get_db)
):
    """Update a member's details."""
    if shop.id != shop_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this shop")

    membership_service = MembershipService(db)
    try:
        await membership_service.update_member(shop_id, customer_id, data.name or "", data.mobile_number)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    
    return {"message": "Member updated successfully"}


@router.delete("/retailer/{shop_id}/all")
async def delete_all_members():
    """Member deletion is disabled on the backend."""
    raise HTTPException(status_code=403, detail="Member deletion is disabled")


@router.delete("/retailer/{shop_id}/members/{customer_id}")
async def delete_member():
    """Member deletion is disabled on the backend."""
    raise HTTPException(status_code=403, detail="Member deletion is disabled")
