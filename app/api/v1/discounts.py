"""Discount management API endpoints."""

import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional,List
from app.database.session import get_db
from app.core.deps import get_current_user, require_permission
from app.schemas.discount import (
    DiscountCreate, DiscountUpdate, DiscountResponse, DiscountReorder,
    VerifyDiscountCodeRequest, DiscountVerificationResponse,
    RedeemDiscountCodeRequest, DiscountRedemptionResponse,
)
from app.schemas.common import MessageResponse
from app.services.discount_service import DiscountService
from app.services.shop_service import ShopService
from app.models.user import User
from app.models.discount import Discount, DiscountRedemption, CustomerDiscountCode

router = APIRouter(prefix="/discounts", tags=["Discounts"])


def _discount_response(d) -> DiscountResponse:
    """Convert Discount model to response."""
    return DiscountResponse(
        id=str(d.id),
        shop_id=str(d.menu_catalog_id),  # expose catalog_id as shop_id for frontend compat
        title=d.title,
        code=d.code,
        description=d.description,
        discount_type=d.discount_type,
        discount_value=str(d.discount_value) if d.discount_value is not None else None,
        buy_quantity=d.buy_quantity,
        get_quantity=d.get_quantity,
        reward_target_ids=d.reward_target_ids,
        applies_to=d.applies_to,
        target_ids=d.target_ids,
        start_date=d.start_date.isoformat() if d.start_date else None,
        end_date=d.end_date.isoformat() if d.end_date else None,
        available_days=d.available_days,
        available_time_presets=d.available_time_presets,
        is_active=d.is_active,
        visibility_type=d.visibility_type,
        display_order=d.display_order,
        created_at=str(d.created_at),
        updated_at=str(d.updated_at),
    )


@router.post("", response_model=DiscountResponse)
async def create_discount(
    data: DiscountCreate,
    shop = Depends(require_permission("discounts", "write")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new discount."""
    service = DiscountService(db)
    discount = await service.create_discount(shop.id, user.id, data.model_dump())
    from app.database.redis import invalidate_shop_cache
    await invalidate_shop_cache(shop.id)
    return _discount_response(discount)


@router.get("", response_model=List[DiscountResponse])
async def get_discounts(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    search: Optional[str] = Query(None),
    shop = Depends(require_permission("discounts", "read")),
    db: AsyncSession = Depends(get_db),
):
    """Get all discounts for the user's shop with pagination and optional search."""
    service = DiscountService(db)
    discounts = await service.get_discounts(shop.id, skip=skip, limit=limit, search=search)
    return [_discount_response(d) for d in discounts]


@router.put("/{discount_id}", response_model=DiscountResponse)
async def update_discount(
    discount_id: str,
    data: DiscountUpdate,
    shop = Depends(require_permission("discounts", "write")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a discount."""
    service = DiscountService(db)
    discount = await service.update_discount(
        shop.id, user.id, uuid.UUID(discount_id), data.model_dump(exclude_unset=True)
    )
    from app.database.redis import invalidate_shop_cache
    await invalidate_shop_cache(shop.id)
    return _discount_response(discount)


@router.put("/reorder/batch", response_model=MessageResponse)
@router.post("/reorder", response_model=MessageResponse)
async def reorder_discounts(
    data: DiscountReorder,
    shop = Depends(require_permission("discounts", "write")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reorder discounts."""
    service = DiscountService(db)
    order_list = [
        {
            "id": item["id"] if isinstance(item, dict) else getattr(item, "id"),
            "display_order": item["display_order"] if isinstance(item, dict) else getattr(item, "display_order")
        }
        for item in data.order
    ]
    await service.reorder_discounts(shop.id, user.id, order_list)
    await db.commit()
    from app.database.redis import invalidate_shop_cache
    await invalidate_shop_cache(shop.id)
    return MessageResponse(message="Discounts reordered successfully")


@router.delete("/all", response_model=MessageResponse)
async def delete_all_discounts(
    shop = Depends(require_permission("discounts", "write")),
    db: AsyncSession = Depends(get_db),
):
    """Delete all discounts for the user's shop's catalog."""
    service = DiscountService(db)
    discounts = await service.get_discounts(shop.id)
    
    for discount in discounts:
        await db.delete(discount)
        
    await db.commit()
    from app.database.redis import invalidate_shop_cache
    await invalidate_shop_cache(shop.id)
    return MessageResponse(message=f"Deleted {len(discounts)} discounts successfully")


@router.delete("/{discount_id}", response_model=MessageResponse)
async def delete_discount(
    discount_id: str,
    shop = Depends(require_permission("discounts", "write")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a discount."""
    service = DiscountService(db)
    await service.delete_discount(shop.id, user.id, uuid.UUID(discount_id))
    from app.database.redis import invalidate_shop_cache
    await invalidate_shop_cache(shop.id)
    return MessageResponse(message="Discount deleted successfully")


async def _find_discount_and_redemption(db: AsyncSession, shop, code_raw: str):
    code_clean = code_raw.strip().upper()
    now = datetime.now(timezone.utc)

    # 1. Check if code has already been redeemed in DiscountRedemption
    redemption_res = await db.execute(
        select(DiscountRedemption)
        .options(selectinload(DiscountRedemption.discount))
        .where(
            DiscountRedemption.shop_id == shop.id,
            func.upper(DiscountRedemption.code) == code_clean
        )
        .order_by(DiscountRedemption.redeemed_at.desc())
    )
    existing_redemption = redemption_res.scalars().first()

    # 2. Check CustomerDiscountCode table for officially assigned code
    assigned_res = await db.execute(
        select(CustomerDiscountCode)
        .options(
            selectinload(CustomerDiscountCode.discount),
            selectinload(CustomerDiscountCode.customer)
        )
        .where(
            CustomerDiscountCode.shop_id == shop.id,
            func.upper(CustomerDiscountCode.code) == code_clean
        )
        .order_by(CustomerDiscountCode.is_redeemed.desc(), CustomerDiscountCode.created_at.desc())
    )
    assigned_objs = list(assigned_res.scalars().all())
    assigned_obj = assigned_objs[0] if assigned_objs else None

    discount = None
    cust_id = None
    if assigned_obj:
        discount = assigned_obj.discount
        cust_id = assigned_obj.customer_identifier
        redeemed_assigned = next((a for a in assigned_objs if a.is_redeemed), None)
        if redeemed_assigned and not existing_redemption:
            existing_redemption = DiscountRedemption(
                id=uuid.uuid4(),
                discount_id=redeemed_assigned.discount_id,
                shop_id=redeemed_assigned.shop_id,
                code=redeemed_assigned.code,
                redeemed_at=redeemed_assigned.redeemed_at or now,
                customer_identifier=redeemed_assigned.customer_identifier,
                discount=redeemed_assigned.discount
            )

    # 3. If not in CustomerDiscountCode, check if it's an exact match on merchant-created static discount code
    if not discount:
        result = await db.execute(
            select(Discount).where(
                Discount.menu_catalog_id == shop.menu_catalog_id,
                Discount.is_active == True,
                func.upper(Discount.code) == code_clean
            )
            .order_by(Discount.created_at.desc())
        )
        discount = result.scalars().first()

    # 4. Resolve customer name and mobile number
    customer_name = None
    customer_phone = None

    if assigned_obj:
        if assigned_obj.customer:
            customer_name = assigned_obj.customer.name
            customer_phone = assigned_obj.customer.mobile_number or assigned_obj.customer_identifier
        elif assigned_obj.customer_identifier:
            customer_phone = assigned_obj.customer_identifier
            from app.models.customer import Customer
            from app.api.v1.public import _get_phone_variants
            variants = _get_phone_variants(assigned_obj.customer_identifier)
            if variants:
                c_res = await db.execute(select(Customer).where(Customer.mobile_number.in_(variants)))
                c_obj = c_res.scalars().first()
                if c_obj:
                    customer_name = c_obj.name
                    if c_obj.mobile_number:
                        customer_phone = c_obj.mobile_number

    if not customer_name and existing_redemption and existing_redemption.customer_identifier:
        customer_phone = existing_redemption.customer_identifier
        from app.models.customer import Customer
        from app.api.v1.public import _get_phone_variants
        variants = _get_phone_variants(existing_redemption.customer_identifier)
        if variants:
            c_res = await db.execute(select(Customer).where(Customer.mobile_number.in_(variants)))
            c_obj = c_res.scalars().first()
            if c_obj:
                customer_name = c_obj.name
                if c_obj.mobile_number:
                    customer_phone = c_obj.mobile_number

    return code_clean, existing_redemption, discount, cust_id, now, assigned_obj, customer_name, customer_phone


@router.post("/verify-code", response_model=DiscountVerificationResponse)
async def verify_merchant_discount_code(
    data: VerifyDiscountCodeRequest,
    shop = Depends(require_permission("discounts", "read")),
    db: AsyncSession = Depends(get_db),
):
    """Verify customer discount code and return validity and redemption status."""
    code_clean, existing_redemption, discount, cust_id, now, assigned_obj, customer_name, customer_phone = await _find_discount_and_redemption(db, shop, data.code)

    if existing_redemption or (assigned_obj and assigned_obj.is_redeemed):
        red_at = (existing_redemption.redeemed_at if existing_redemption else assigned_obj.redeemed_at) or now
        d_resp = _discount_response(existing_redemption.discount) if (existing_redemption and existing_redemption.discount) else (_discount_response(discount) if discount else None)
        return DiscountVerificationResponse(
            valid=False,
            is_redeemed=True,
            redeemed_at=red_at.strftime("%d %b %Y, %I:%M %p"),
            discount=d_resp,
            code=code_clean,
            message=f"This discount code was already verified and redeemed on {red_at.strftime('%d %b %Y, %I:%M %p')}. It cannot be reused.",
            customer_name=customer_name,
            customer_phone=customer_phone
        )

    if not discount:
        return DiscountVerificationResponse(
            valid=False,
            is_redeemed=False,
            code=code_clean,
            message=f"Discount code '{code_clean}' does not exist or has not been assigned to any customer."
        )

    if discount.start_date and discount.start_date > now:
        return DiscountVerificationResponse(
            valid=False,
            is_redeemed=False,
            discount=_discount_response(discount),
            code=code_clean,
            message="This discount offer has not started yet.",
            customer_name=customer_name,
            customer_phone=customer_phone
        )

    if discount.end_date and discount.end_date < now:
        return DiscountVerificationResponse(
            valid=False,
            is_redeemed=False,
            discount=_discount_response(discount),
            code=code_clean,
            message="This discount offer has expired.",
            customer_name=customer_name,
            customer_phone=customer_phone
        )

    resp_discount = _discount_response(discount)
    resp_discount.code = code_clean

    return DiscountVerificationResponse(
        valid=True,
        is_redeemed=False,
        discount=resp_discount,
        code=code_clean,
        message="Discount code is valid and ready to be redeemed.",
        customer_name=customer_name,
        customer_phone=customer_phone
    )


@router.post("/redeem-code", response_model=DiscountVerificationResponse)
async def redeem_merchant_discount_code(
    data: RedeemDiscountCodeRequest,
    shop = Depends(require_permission("discounts", "write")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Verify and redeem customer discount code, permanently preventing reuse."""
    code_clean, existing_redemption, discount, cust_id, now, assigned_obj, customer_name, customer_phone = await _find_discount_and_redemption(db, shop, data.code)

    if existing_redemption or (assigned_obj and assigned_obj.is_redeemed):
        red_at = (existing_redemption.redeemed_at if existing_redemption else assigned_obj.redeemed_at) or now
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"This discount code was already verified and redeemed on {red_at.strftime('%d %b %Y, %I:%M %p')} and cannot be reused."
        )

    if not discount:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Discount code '{code_clean}' does not exist or has not been assigned to any customer."
        )

    if discount.start_date and discount.start_date > now:
        raise HTTPException(status_code=400, detail="This discount offer has not started yet.")
    if discount.end_date and discount.end_date < now:
        raise HTTPException(status_code=400, detail="This discount offer has expired.")

    # Mark assigned code as redeemed if tracked
    if assigned_obj:
        assigned_obj.is_redeemed = True
        assigned_obj.redeemed_at = now

    # Record redemption
    customer_token = data.customer_identifier or cust_id or customer_phone
    redemption = DiscountRedemption(
        id=uuid.uuid4(),
        discount_id=discount.id,
        shop_id=shop.id,
        code=code_clean,
        redeemed_at=now,
        customer_identifier=customer_token,
        redeemed_by_user_id=user.id
    )
    db.add(redemption)
    await db.commit()

    resp_discount = _discount_response(discount)
    resp_discount.code = code_clean

    return DiscountVerificationResponse(
        valid=True,
        is_redeemed=True,
        redeemed_at=now.strftime("%d %b %Y, %I:%M %p"),
        discount=resp_discount,
        code=code_clean,
        message=f"Discount code '{code_clean}' successfully redeemed! It is now permanently locked and cannot be reused.",
        customer_name=customer_name,
        customer_phone=customer_phone
    )


@router.get("/redemptions", response_model=List[DiscountRedemptionResponse])
async def get_discount_redemptions(
    limit: int = Query(20, ge=1, le=100),
    shop = Depends(require_permission("discounts", "read")),
    db: AsyncSession = Depends(get_db),
):
    """Get recent discount code redemptions for this shop."""
    result = await db.execute(
        select(DiscountRedemption)
        .options(selectinload(DiscountRedemption.discount))
        .where(DiscountRedemption.shop_id == shop.id)
        .order_by(DiscountRedemption.redeemed_at.desc())
        .limit(limit)
    )
    redemptions = result.scalars().all()
    out = []
    for r in redemptions:
        d = r.discount
        out.append(DiscountRedemptionResponse(
            id=str(r.id),
            discount_id=str(r.discount_id),
            discount_title=d.title if d else "Discount",
            discount_type=d.discount_type if d else "percentage",
            discount_value=str(d.discount_value) if d and d.discount_value is not None else None,
            code=r.code,
            redeemed_at=r.redeemed_at.strftime("%d %b %Y, %I:%M %p"),
            customer_identifier=r.customer_identifier
        ))
    return out
