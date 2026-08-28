import uuid
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
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
        )

        if search and search.strip():
            term = f"%{search.strip()}%"
            stmt = stmt.where(or_(Customer.name.ilike(term), Customer.mobile_number.ilike(term)))

        stmt = (
            stmt.group_by(Customer.id, Customer.name, Customer.mobile_number)
            .having(func.count(func.distinct(func.date(MembershipEvent.event_time))) >= min_visits)
            .order_by(func.count(func.distinct(func.date(MembershipEvent.event_time))).desc())
        )

        result = await db.execute(stmt)
        all_rows = result.all()
        total_count = len(all_rows)
        paginated_rows = all_rows[skip : skip + limit]

        for r in paginated_rows:
            items.append(MemberItemSchema(
                id=r.id,
                name=r.name,
                mobile_number=r.mobile_number,
                joined_at=r.joined_at,
                is_retailer_added=False,
                visit_count=r.visit_count
            ))

    else:
        is_retailer_added = (tab == "existing")

        conditions = [
            CustomerRetailerMembership.shop_id == shop_id,
            CustomerRetailerMembership.is_retailer_added == is_retailer_added
        ]

        if search and search.strip():
            term = f"%{search.strip()}%"
            conditions.append(
                or_(Customer.name.ilike(term), Customer.mobile_number.ilike(term))
            )

        count_stmt = select(func.count(CustomerRetailerMembership.id)).join(
            Customer, Customer.id == CustomerRetailerMembership.customer_id
        ).where(*conditions)
        count_res = await db.execute(count_stmt)
        total_count = count_res.scalar() or 0

        items_stmt = (
            select(CustomerRetailerMembership)
            .join(Customer, Customer.id == CustomerRetailerMembership.customer_id)
            .options(joinedload(CustomerRetailerMembership.customer))
            .where(*conditions)
            .order_by(CustomerRetailerMembership.created_at.desc())
            .offset(skip)
            .limit(limit)
        )

        items_res = await db.execute(items_stmt)
        memberships = items_res.scalars().all()

        for m in memberships:
            items.append(MemberItemSchema(
                id=m.customer.id,
                name=m.customer.name,
                mobile_number=m.customer.mobile_number,
                joined_at=m.created_at,
                is_retailer_added=m.is_retailer_added
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
