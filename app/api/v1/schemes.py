"""API endpoints for Savings Schemes (formerly called Pandu)."""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.core.deps import require_permission, get_current_user
from app.models.user import User
from app.models.shop import Shop
from app.schemas.scheme import (
    SchemeCreate,
    SchemeUpdate,
    SchemeResponse,
    SchemeMemberCreate,
    SchemeMemberResponse,
    RecordPaymentRequest,
    PublicSchemeResponse,
    CustomerSchemePassResponse,
    SchemePaymentInitiateRequest,
    SchemePaymentInitiateResponse,
    SchemePaymentVerifyRequest,
)
from app.services.scheme_service import SchemeService

router = APIRouter(prefix="/schemes", tags=["Schemes (Fund)"])
public_router = APIRouter(prefix="/public/shop/{shop_id}/schemes", tags=["Public Schemes"])


# -------------------- Merchant Dashboard Endpoints --------------------

@router.get("", response_model=List[SchemeResponse])
async def list_schemes(
    shop: Shop = Depends(require_permission("schemes", "read")),
    db: AsyncSession = Depends(get_db),
):
    """List all schemes created for the current shop with stats."""
    service = SchemeService(db)
    return await service.get_schemes(shop.id)


@router.post("", response_model=SchemeResponse, status_code=status.HTTP_201_CREATED)
async def create_scheme(
    data: SchemeCreate,
    shop: Shop = Depends(require_permission("schemes", "write")),
    db: AsyncSession = Depends(get_db),
):
    """Create a new savings scheme for the shop."""
    service = SchemeService(db)
    return await service.create_scheme(shop.id, data)


@router.get("/{scheme_id}", response_model=SchemeResponse)
async def get_scheme_details(
    scheme_id: str,
    shop: Shop = Depends(require_permission("schemes", "read")),
    db: AsyncSession = Depends(get_db),
):
    """Get single scheme details with member count and collection statistics."""
    service = SchemeService(db)
    return await service.get_scheme(uuid.UUID(scheme_id), shop.id)


@router.put("/{scheme_id}", response_model=SchemeResponse)
async def update_scheme(
    scheme_id: str,
    data: SchemeUpdate,
    shop: Shop = Depends(require_permission("schemes", "write")),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing scheme."""
    service = SchemeService(db)
    return await service.update_scheme(uuid.UUID(scheme_id), shop.id, data)


@router.delete("/{scheme_id}")
async def delete_scheme(
    scheme_id: str,
    shop: Shop = Depends(require_permission("schemes", "write")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a scheme and its records."""
    service = SchemeService(db)
    await service.delete_scheme(uuid.UUID(scheme_id), shop.id)
    return {"status": "success", "message": "Scheme deleted successfully"}


@router.get("/{scheme_id}/members", response_model=List[SchemeMemberResponse])
async def list_scheme_members(
    scheme_id: str,
    search: Optional[str] = Query(None, description="Search by customer name, phone, or member #"),
    shop: Shop = Depends(require_permission("schemes", "read")),
    db: AsyncSession = Depends(get_db),
):
    """List members of a scheme with search and visual installment payment tracking."""
    service = SchemeService(db)
    return await service.get_scheme_members(uuid.UUID(scheme_id), shop.id, search=search)


@router.post("/{scheme_id}/members", response_model=SchemeMemberResponse, status_code=status.HTTP_201_CREATED)
async def add_scheme_member(
    scheme_id: str,
    data: SchemeMemberCreate,
    shop: Shop = Depends(require_permission("schemes", "write")),
    db: AsyncSession = Depends(get_db),
):
    """Enroll a customer into the scheme."""
    service = SchemeService(db)
    return await service.add_member(uuid.UUID(scheme_id), shop.id, data)


@router.post("/{scheme_id}/members/{member_id}/payments", response_model=SchemeMemberResponse)
async def record_member_payment(
    scheme_id: str,
    member_id: str,
    data: RecordPaymentRequest,
    shop: Shop = Depends(require_permission("schemes", "write")),
    db: AsyncSession = Depends(get_db),
):
    """Record an installment payment for a member."""
    service = SchemeService(db)
    return await service.record_payment(uuid.UUID(scheme_id), shop.id, uuid.UUID(member_id), data)


# -------------------- Public Menu Endpoints --------------------

@public_router.get("", response_model=List[PublicSchemeResponse])
async def get_public_schemes(
    shop_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get active schemes that are configured to show on the public menu."""
    service = SchemeService(db)
    return await service.get_public_schemes(uuid.UUID(shop_id))


@public_router.post("/{scheme_id}/join", response_model=SchemeMemberResponse, status_code=status.HTTP_201_CREATED)
async def public_join_scheme(
    shop_id: str,
    scheme_id: str,
    data: SchemeMemberCreate,
    db: AsyncSession = Depends(get_db),
):
    """Customer joins a scheme from the public menu."""
    service = SchemeService(db)
    return await service.public_join_scheme(uuid.UUID(scheme_id), uuid.UUID(shop_id), data)


@public_router.get("/my-status", response_model=List[CustomerSchemePassResponse])
async def get_my_scheme_status(
    shop_id: str,
    phone: str = Query(..., description="Customer phone number"),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve enrolled schemes and remaining installments for a customer on the public menu."""
    service = SchemeService(db)
    return await service.get_customer_scheme_passes(uuid.UUID(shop_id), phone)


@public_router.post("/{scheme_id}/initiate-payment", response_model=SchemePaymentInitiateResponse)
async def initiate_scheme_join_payment(
    shop_id: str,
    scheme_id: str,
    data: SchemePaymentInitiateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a Razorpay order to enroll in a scheme with 2% platform commission & 3% PG fee (+18% GST)."""
    service = SchemeService(db)
    return await service.initiate_join_payment(uuid.UUID(scheme_id), uuid.UUID(shop_id), data)


@public_router.post("/{scheme_id}/verify-payment", response_model=SchemeMemberResponse, status_code=status.HTTP_201_CREATED)
async def verify_scheme_join_payment(
    shop_id: str,
    scheme_id: str,
    data: SchemePaymentVerifyRequest,
    db: AsyncSession = Depends(get_db),
):
    """Verify Razorpay payment signature and complete enrollment with 1st installment paid."""
    service = SchemeService(db)
    return await service.verify_join_payment(uuid.UUID(scheme_id), uuid.UUID(shop_id), data)


@public_router.post("/{scheme_id}/members/{member_id}/initiate-payment", response_model=SchemePaymentInitiateResponse)
async def initiate_member_installment_payment(
    shop_id: str,
    scheme_id: str,
    member_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Initiate a Razorpay order for an enrolled member's next due installment."""
    service = SchemeService(db)
    return await service.initiate_installment_payment(
        uuid.UUID(scheme_id), uuid.UUID(shop_id), uuid.UUID(member_id)
    )


@public_router.post("/{scheme_id}/members/{member_id}/verify-payment", response_model=CustomerSchemePassResponse)
async def verify_member_installment_payment(
    shop_id: str,
    scheme_id: str,
    member_id: str,
    data: SchemePaymentVerifyRequest,
    db: AsyncSession = Depends(get_db),
):
    """Verify Razorpay payment signature and record the next installment."""
    service = SchemeService(db)
    return await service.verify_installment_payment(
        uuid.UUID(scheme_id), uuid.UUID(shop_id), uuid.UUID(member_id), data
    )

