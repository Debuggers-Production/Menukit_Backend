"""API endpoints for Savings Schemes (formerly called Pandu)."""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy import select
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
    SchemeMemberDeleteOtpResponse,
    SchemeMemberDeleteRequest,
    SchemeMemberTransferRequest,
    SchemeActivityLogResponse,
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


@router.post("/sync-members")
async def sync_scheme_members_to_shop(
    shop: Shop = Depends(require_permission("schemes", "write")),
    db: AsyncSession = Depends(get_db),
):
    """Sync all scheme members into the shop's customer members list."""
    service = SchemeService(db)
    synced_count = await service.sync_scheme_members_to_shop_members(shop.id)
    return {
        "status": "success",
        "message": f"Successfully synchronized {synced_count} scheme members to shop members list.",
        "synced_count": synced_count,
    }


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


@router.post("/{scheme_id}/members/{member_id}/send-delete-otp", response_model=SchemeMemberDeleteOtpResponse)
async def send_member_delete_otp(
    scheme_id: str,
    member_id: str,
    shop: Shop = Depends(require_permission("schemes", "write")),
    db: AsyncSession = Depends(get_db),
):
    """Send an SMS OTP to the customer's phone to authorize removing their scheme enrollment."""
    service = SchemeService(db)
    return await service.send_member_delete_otp(uuid.UUID(scheme_id), shop.id, uuid.UUID(member_id))


@router.post("/{scheme_id}/members/{member_id}/delete")
@router.delete("/{scheme_id}/members/{member_id}")
async def delete_scheme_member(
    scheme_id: str,
    member_id: str,
    data: Optional[SchemeMemberDeleteRequest] = None,
    otp: Optional[str] = Query(None, description="Optional OTP if passed via query param"),
    verification_id: Optional[str] = Query(None, description="Optional verification ID if passed via query param"),
    shop: Shop = Depends(require_permission("schemes", "write")),
    db: AsyncSession = Depends(get_db),
):
    """Delete an enrolled scheme member. Requires customer OTP if installments were paid."""
    service = SchemeService(db)
    final_otp = (data.otp if data and data.otp else otp)
    final_vid = (data.verification_id if data and data.verification_id else verification_id)
    final_reason = (data.reason if data and data.reason else None)
    await service.delete_member(
        uuid.UUID(scheme_id),
        shop.id,
        uuid.UUID(member_id),
        otp=final_otp,
        verification_id=final_vid,
        reason=final_reason,
    )
    return {"status": "success", "message": "Scheme member removed successfully"}


@router.post("/{scheme_id}/members/{member_id}/transfer", response_model=SchemeMemberResponse)
async def transfer_scheme_member(
    scheme_id: str,
    member_id: str,
    data: SchemeMemberTransferRequest,
    shop: Shop = Depends(require_permission("schemes", "write")),
    db: AsyncSession = Depends(get_db),
):
    """Transfer an enrolled member from one scheme to another within the same shop."""
    service = SchemeService(db)
    return await service.transfer_member(
        uuid.UUID(scheme_id),
        shop.id,
        uuid.UUID(member_id),
        uuid.UUID(data.target_scheme_id),
        notes=data.notes,
    )


@router.get("/members/history", response_model=List[SchemeActivityLogResponse])
async def get_customer_scheme_history_merchant(
    phone: str = Query(..., description="Customer phone number"),
    shop: Shop = Depends(require_permission("schemes", "read")),
    db: AsyncSession = Depends(get_db),
):
    """Get permanent audit history of scheme enrollments, payments, transfers, and cancellations for a customer."""
    service = SchemeService(db)
    return await service.get_customer_history(shop.id, phone)


@router.get("/customers/lookup")
async def lookup_customer_by_phone(
    phone: str = Query(..., description="Customer phone number"),
    scheme_id: Optional[uuid.UUID] = Query(None, description="Optional scheme ID to check if customer is already enrolled"),
    shop: Shop = Depends(require_permission("schemes", "read")),
    db: AsyncSession = Depends(get_db),
):
    """Lookup an existing customer by phone number across shop and global records to autofill details and check duplicate enrollment."""
    service = SchemeService(db)
    result = await service.lookup_customer(shop.id, phone, scheme_id=scheme_id)
    return result or {"found": False, "name": None, "address": None, "is_already_enrolled": False}




# -------------------- Public Menu Endpoints --------------------

async def _resolve_shop_uuid(shop_id: str, db: AsyncSession) -> uuid.UUID:
    """Resolve shop_id string (either UUID or shop slug) into a valid UUID."""
    try:
        return uuid.UUID(shop_id)
    except ValueError:
        res = await db.execute(select(Shop.id).where(Shop.slug == shop_id, Shop.is_deleted == False))
        shop_uuid = res.scalar_one_or_none()
        if not shop_uuid:
            raise HTTPException(status_code=404, detail="Shop not found")
        return shop_uuid


@public_router.get("", response_model=List[PublicSchemeResponse])
async def get_public_schemes(
    shop_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get active schemes that are configured to show on the public menu."""
    target_shop_id = await _resolve_shop_uuid(shop_id, db)
    service = SchemeService(db)
    return await service.get_public_schemes(target_shop_id)


@public_router.post("/{scheme_id}/join", response_model=SchemeMemberResponse, status_code=status.HTTP_201_CREATED)
async def public_join_scheme(
    shop_id: str,
    scheme_id: str,
    data: SchemeMemberCreate,
    db: AsyncSession = Depends(get_db),
):
    """Customer joins a scheme from the public menu."""
    target_shop_id = await _resolve_shop_uuid(shop_id, db)
    service = SchemeService(db)
    return await service.public_join_scheme(uuid.UUID(scheme_id), target_shop_id, data)


@public_router.get("/my-status", response_model=List[CustomerSchemePassResponse])
async def get_my_scheme_status(
    shop_id: str,
    phone: str = Query(..., description="Customer phone number"),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve enrolled schemes and remaining installments for a customer on the public menu."""
    target_shop_id = await _resolve_shop_uuid(shop_id, db)
    service = SchemeService(db)
    return await service.get_customer_scheme_passes(target_shop_id, phone)


@public_router.get("/my-history", response_model=List[SchemeActivityLogResponse])
async def get_my_scheme_history_public(
    shop_id: str,
    phone: str = Query(..., description="Customer phone number"),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve permanent scheme timeline & activity history (transfers, payments, cancellations) for a customer."""
    target_shop_id = await _resolve_shop_uuid(shop_id, db)
    service = SchemeService(db)
    return await service.get_customer_history(target_shop_id, phone)



@public_router.post("/{scheme_id}/initiate-payment", response_model=SchemePaymentInitiateResponse)
async def initiate_scheme_join_payment(
    shop_id: str,
    scheme_id: str,
    data: SchemePaymentInitiateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a Razorpay order to enroll in a scheme with 2% platform commission & 3% PG fee (+18% GST)."""
    target_shop_id = await _resolve_shop_uuid(shop_id, db)
    service = SchemeService(db)
    return await service.initiate_join_payment(uuid.UUID(scheme_id), target_shop_id, data)


@public_router.post("/{scheme_id}/verify-payment", response_model=SchemeMemberResponse, status_code=status.HTTP_201_CREATED)
async def verify_scheme_join_payment(
    shop_id: str,
    scheme_id: str,
    data: SchemePaymentVerifyRequest,
    db: AsyncSession = Depends(get_db),
):
    """Verify Razorpay payment signature and complete enrollment with 1st installment paid."""
    target_shop_id = await _resolve_shop_uuid(shop_id, db)
    service = SchemeService(db)
    return await service.verify_join_payment(uuid.UUID(scheme_id), target_shop_id, data)


@public_router.post("/{scheme_id}/members/{member_id}/initiate-payment", response_model=SchemePaymentInitiateResponse)
async def initiate_member_installment_payment(
    shop_id: str,
    scheme_id: str,
    member_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Initiate a Razorpay order for an enrolled member's next due installment."""
    target_shop_id = await _resolve_shop_uuid(shop_id, db)
    service = SchemeService(db)
    return await service.initiate_installment_payment(
        uuid.UUID(scheme_id), target_shop_id, uuid.UUID(member_id)
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
    target_shop_id = await _resolve_shop_uuid(shop_id, db)
    service = SchemeService(db)
    return await service.verify_installment_payment(
        uuid.UUID(scheme_id), target_shop_id, uuid.UUID(member_id), data
    )

