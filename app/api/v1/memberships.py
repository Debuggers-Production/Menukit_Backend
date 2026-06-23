"""Membership API endpoints."""

import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.membership import (
    AddMemberRequest, MembershipAnalyticsResponse, MembershipEventRequest, MemberResponse,
    RepeatedCustomerResponse
)
from app.services.membership_service import MembershipService
from app.services.shop_service import ShopService
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from app.models.membership import CustomerRetailerMembership
from typing import List

router = APIRouter(prefix="/memberships", tags=["Memberships"])


@router.post("/retailer/{shop_id}/add")
async def add_member(
    shop_id: uuid.UUID,
    data: AddMemberRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Retailer adds a member directly to their shop."""
    # Verify shop belongs to user
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_user(user.id)
    if not shop or shop.id != shop_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this shop")

    membership_service = MembershipService(db)
    membership = await membership_service.add_member(shop_id, data.name, data.mobile_number)
    
    return {"message": "Member added successfully", "customer_id": membership.customer_id}


@router.get("/retailer/{shop_id}/analytics", response_model=MembershipAnalyticsResponse)
async def get_membership_analytics(
    shop_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get aggregate membership analytics for retailer dashboard."""
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_user(user.id)
    if not shop or shop.id != shop_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this shop")

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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get list of manually added members for retailer dashboard."""
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_user(user.id)
    if not shop or shop.id != shop_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this shop")

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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get list of auto-registered members for retailer dashboard."""
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_user(user.id)
    if not shop or shop.id != shop_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this shop")

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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get list of customers with multiple visits."""
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_user(user.id)
    if not shop or shop.id != shop_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this shop")

    membership_service = MembershipService(db)
    customers = await membership_service.get_repeated_customers(shop_id, min_visits)

    return [RepeatedCustomerResponse(**c) for c in customers]


@router.post("/retailer/{shop_id}/members/{customer_id}/convert")
async def convert_to_member(
    shop_id: uuid.UUID,
    customer_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Convert an auto-registered member to a manually verified member."""
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_user(user.id)
    if not shop or shop.id != shop_id:
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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update a member's details."""
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_user(user.id)
    if not shop or shop.id != shop_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this shop")

    membership_service = MembershipService(db)
    try:
        await membership_service.update_member(shop_id, customer_id, data.name or "", data.mobile_number)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    
    return {"message": "Member updated successfully"}


@router.delete("/retailer/{shop_id}/all")
async def delete_all_members(
    shop_id: uuid.UUID,
    type: str = "all",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete all members for a shop."""
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_user(user.id)
    if not shop or shop.id != shop_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this shop")

    # Delete all memberships for this shop
    stmt = select(CustomerRetailerMembership).where(CustomerRetailerMembership.shop_id == shop_id)
    
    if type == "existing":
        stmt = stmt.where(CustomerRetailerMembership.is_retailer_added == True)
    elif type == "new":
        stmt = stmt.where(CustomerRetailerMembership.is_retailer_added == False)

    result = await db.execute(stmt)
    memberships = result.scalars().all()
    
    for membership in memberships:
        await db.delete(membership)
        
    await db.commit()
    return {"message": f"Deleted {len(memberships)} members successfully"}


@router.delete("/retailer/{shop_id}/members/{customer_id}")
async def remove_member(
    shop_id: uuid.UUID,
    customer_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Remove a member from the shop."""
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_user(user.id)
    if not shop or shop.id != shop_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this shop")

    membership_service = MembershipService(db)
    try:
        await membership_service.remove_member(shop_id, customer_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    
    return {"message": "Member removed successfully"}
