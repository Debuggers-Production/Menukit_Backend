"""Discount management API endpoints."""

import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy import select, func, or_
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


def _to_utc_iso(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _discount_response(d, is_already_used: bool = False) -> DiscountResponse:
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
        start_date=_to_utc_iso(d.start_date),
        end_date=_to_utc_iso(d.end_date),
        available_days=d.available_days,
        available_time_presets=d.available_time_presets,
        is_active=d.is_active,
        visibility_type=d.visibility_type,
        display_order=d.display_order,
        is_already_used=is_already_used,
        created_at=_to_utc_iso(d.created_at) or str(d.created_at),
        updated_at=_to_utc_iso(d.updated_at) or str(d.updated_at),
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
    from app.models.order import Order
    redemption_res = await db.execute(
        select(DiscountRedemption)
        .options(selectinload(DiscountRedemption.discount))
        .outerjoin(Order, DiscountRedemption.order_id == Order.id)
        .where(
            DiscountRedemption.shop_id == shop.id,
            func.upper(DiscountRedemption.code) == code_clean,
            DiscountRedemption.status == "active",
            or_(
                DiscountRedemption.order_id.is_(None),
                func.lower(Order.order_status).notin_(["cancelled", "rejected"])
            )
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
        if redeemed_assigned:
            if existing_redemption:
                pass
            else:
                # Check if there is an active redemption
                chk_act_res = await db.execute(
                    select(DiscountRedemption)
                    .options(selectinload(DiscountRedemption.discount))
                    .outerjoin(Order, DiscountRedemption.order_id == Order.id)
                    .where(
                        DiscountRedemption.shop_id == shop.id,
                        DiscountRedemption.discount_id == redeemed_assigned.discount_id,
                        DiscountRedemption.status == "active",
                        or_(
                            DiscountRedemption.order_id.is_(None),
                            func.lower(Order.order_status).notin_(["cancelled", "rejected"])
                        ),
                        or_(
                            func.upper(DiscountRedemption.code) == code_clean,
                            DiscountRedemption.customer_identifier == (redeemed_assigned.customer_identifier or "")
                        )
                    )
                )
                act_red = chk_act_res.scalars().first()
                if act_red:
                    existing_redemption = act_red
                else:
                    # Auto-heal: no active redemption exists (e.g. order was cancelled), so unmark is_redeemed
                    for a in assigned_objs:
                        a.is_redeemed = False
                        a.redeemed_at = None
                    await db.commit()

    # Resolve catalog_id safely
    catalog_id = shop.menu_catalog_id
    if not catalog_id:
        c_res = await db.execute(select(Shop.menu_catalog_id).where(Shop.id == shop.id))
        catalog_id = c_res.scalar_one_or_none()

    # 3. If not in CustomerDiscountCode, check if it's an exact match on merchant-created static discount code
    if not discount and catalog_id and code_clean:
        result = await db.execute(
            select(Discount).where(
                Discount.menu_catalog_id == catalog_id,
                Discount.code.isnot(None),
                func.upper(Discount.code) == code_clean
            )
            .order_by(Discount.created_at.desc())
        )
        discount = result.scalars().first()

    # 4. Check if this exact code already has a recorded redemption
    if discount and not existing_redemption:
        chk_red = await db.execute(
            select(DiscountRedemption)
            .options(selectinload(DiscountRedemption.discount))
            .outerjoin(Order, DiscountRedemption.order_id == Order.id)
            .where(
                DiscountRedemption.shop_id == shop.id,
                DiscountRedemption.discount_id == discount.id,
                func.upper(DiscountRedemption.code) == code_clean,
                DiscountRedemption.status == "active",
                or_(
                    DiscountRedemption.order_id.is_(None),
                    func.lower(Order.order_status).notin_(["cancelled", "rejected"])
                )
            )
            .order_by(DiscountRedemption.redeemed_at.desc())
        )
        found_red = chk_red.scalars().first()
        if found_red:
            existing_redemption = found_red

    # 5. Resolve customer name and mobile number strictly from assigned record
    customer_name = None
    customer_phone = None

    if assigned_obj:
        if assigned_obj.customer:
            customer_name = assigned_obj.customer.name
            customer_phone = assigned_obj.customer.mobile_number or assigned_obj.customer_identifier
        elif assigned_obj.customer_identifier:
            customer_phone = assigned_obj.customer_identifier

    if not customer_name and existing_redemption and existing_redemption.customer_identifier:
        if not customer_phone:
            customer_phone = existing_redemption.customer_identifier

    if customer_phone:
        from app.models.customer import Customer
        from app.api.v1.public import _get_phone_variants
        variants = _get_phone_variants(customer_phone)
        if variants:
            c_res = await db.execute(select(Customer).where(Customer.mobile_number.in_(variants)))
            c_obj = c_res.scalars().first()
            if c_obj:
                if not customer_name:
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
            redeemed_at=_to_utc_iso(red_at) or "",
            discount=d_resp,
            code=code_clean,
            message="This discount code was already verified and redeemed. It cannot be reused.",
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
            detail="This discount code was already verified and redeemed and cannot be reused."
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
        redeemed_at=_to_utc_iso(now) or "",
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
    from app.models.order import Order
    from sqlalchemy import or_
    result = await db.execute(
        select(DiscountRedemption)
        .options(selectinload(DiscountRedemption.discount))
        .outerjoin(Order, DiscountRedemption.order_id == Order.id)
        .where(
            DiscountRedemption.shop_id == shop.id,
            DiscountRedemption.status == "active",
            or_(
                DiscountRedemption.order_id.is_(None),
                func.lower(Order.order_status).notin_(["cancelled", "rejected"])
            )
        )
        .order_by(DiscountRedemption.redeemed_at.desc())
        .limit(limit)
    )
    redemptions = result.scalars().all()
    out = []
    for r in redemptions:
        d = r.discount
        proper_code = r.code
        if d and (not proper_code or " " in proper_code or "%" in proper_code or (d.title and proper_code.strip() == d.title.strip())):
            from app.services.discount_service import generate_discount_code_string
            proper_code = (d.code if (d.code and "-" in d.code) else None) or generate_discount_code_string(d.title, d.id, r.customer_identifier or "CUST")

        out.append(DiscountRedemptionResponse(
            id=str(r.id),
            discount_id=str(r.discount_id),
            discount_title=d.title if d else "Discount",
            discount_type=d.discount_type if d else "percentage",
            discount_value=str(d.discount_value) if d and d.discount_value is not None else None,
            code=proper_code,
            redeemed_at=_to_utc_iso(r.redeemed_at) or "",
            customer_identifier=r.customer_identifier
        ))
    return out
