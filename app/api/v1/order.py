"""Order API endpoints for merchants."""

import uuid
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from app.database.session import get_db
from app.core.deps import get_current_user, require_permission
from app.schemas.order import OrderResponse, OrderStatusUpdate, PaymentStatusUpdate, OrderItemCancel, OrderItemReplace
from app.services.order_service import OrderService
from app.models.user import User

router = APIRouter(prefix="/orders", tags=["Orders"])


from pydantic import BaseModel


class OrderStatusCountsResponse(BaseModel):
    all: int
    new: int
    awaiting_payment: int
    accepted: int
    preparing: int
    completed: int
    cancelled: int


async def check_orders_subscription(shop, db: AsyncSession):
    """Backend subscription verification for orders management endpoints."""
    from app.services.subscription_helper import get_shop_subscription_permissions
    from fastapi import HTTPException
    if shop:
        perms = await get_shop_subscription_permissions(shop.id, db)
        if perms["is_expired"] or not perms["online_orders"]:

            raise HTTPException(
                status_code=403,
                detail="Subscription required: Orders management is locked due to an inactive or missing online-orders module. Please purchase the Online Visibility & Orders Accept module."
            )


@router.get("/status-counts", response_model=OrderStatusCountsResponse)
async def get_order_status_counts(
    date_filter: Optional[str] = Query(None),
    shop = Depends(require_permission("orders", "read")),
    db: AsyncSession = Depends(get_db),
):
    """Get accurate shop-wide counts for order status tabs, optionally filtered by date."""
    await check_orders_subscription(shop, db)
    service = OrderService(db)
    counts = await service.get_status_counts(shop.id, date_filter=date_filter)
    return counts


@router.get("", response_model=List[OrderResponse])
async def list_orders(
    response: Response,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query("all"),
    type_filter: Optional[str] = Query("all"),
    search: Optional[str] = Query(None),
    date_filter: Optional[str] = Query(None),
    shop = Depends(require_permission("orders", "read")),
    db: AsyncSession = Depends(get_db),
):
    """List all orders for the merchant's restaurant with backend SQL search, date filters, and pagination."""
    await check_orders_subscription(shop, db)
    service = OrderService(db)
    orders, total_count, has_more = await service.get_shop_orders(
        shop.id,
        skip=skip,
        limit=limit,
        status_filter=status_filter,
        type_filter=type_filter,
        search=search,
        date_filter=date_filter
    )
    response.headers["x-total-count"] = str(total_count)
    response.headers["x-has-more"] = "true" if has_more else "false"
    return [OrderResponse.model_validate(o) for o in orders]



@router.put("/{order_id}/status", response_model=OrderResponse)
async def update_order_status(
    order_id: str,
    status_data: OrderStatusUpdate,
    shop = Depends(require_permission("orders", "write")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update order status (e.g. accept, complete, rejected, cancelled)."""
    import uuid
    await check_orders_subscription(shop, db)
    service = OrderService(db)
    order = await service.update_order_status(
        uuid.UUID(order_id), 
        status_data.status, 
        shop.id,
        status_data.cancellation_reason,
        user_id=current_user.id
    )
    await db.commit()
    return OrderResponse.model_validate(order)


@router.put("/{order_id}/payment", response_model=OrderResponse)
async def update_payment_status(
    order_id: str,
    payment_data: PaymentStatusUpdate,
    shop = Depends(require_permission("orders", "write")),
    db: AsyncSession = Depends(get_db),
):
    """Update order payment status and optionally payment method."""
    import uuid
    await check_orders_subscription(shop, db)
    service = OrderService(db)
    order = await service.update_payment_status(
        uuid.UUID(order_id), 
        payment_data.payment_status, 
        shop.id,
        payment_method=payment_data.payment_method,
        split_payments=payment_data.split_payments
    )
    await db.commit()
    return OrderResponse.model_validate(order)


@router.post("/{order_id}/refund", response_model=OrderResponse)
async def retry_order_refund(
    order_id: str,
    shop = Depends(require_permission("orders", "write")),
    db: AsyncSession = Depends(get_db),
):
    """Initiate or retry Razorpay refund for a paid online order."""
    import uuid
    await check_orders_subscription(shop, db)
    service = OrderService(db)
    order = await service.retry_order_refund(
        uuid.UUID(order_id),
        shop.id
    )
    return OrderResponse.model_validate(order)


from app.schemas.order import OrderCreate, OrderAddItems

@router.get("/customer-lookup")
async def lookup_customer(
    phone: str = Query(..., min_length=3),
    shop = Depends(require_permission("orders", "read")),
    db: AsyncSession = Depends(get_db),
):
    """Lookup existing customer by phone number for quick order creation and auto-fill."""
    from app.models.customer import Customer
    from sqlalchemy import select
    clean_phone = "".join(filter(str.isdigit, phone))
    if not clean_phone:
        return {"exists": False}
        
    phone_variants = [phone.strip(), clean_phone]
    if len(clean_phone) == 10:
        phone_variants.extend([f"+91{clean_phone}", f"91{clean_phone}"])
    elif len(clean_phone) == 12 and clean_phone.startswith("91"):
        phone_variants.extend([clean_phone[2:], f"+{clean_phone}"])

    stmt = select(Customer).where(Customer.mobile_number.in_(phone_variants))
    result = await db.execute(stmt)
    customer = result.scalars().first()

    # Check which discounts this customer has already used
    from app.models.discount import DiscountRedemption, CustomerDiscountCode
    from sqlalchemy import or_, func

    claimed_discount_ids = set()
    last4 = clean_phone[-4:].upper() if len(clean_phone) >= 4 else ""
    token_filters = [DiscountRedemption.customer_identifier.in_(phone_variants)]
    if last4:
        token_filters.append(func.upper(DiscountRedemption.code).like(f"%-{last4}"))

    from app.models.order import Order
    claimed_res = await db.execute(
        select(DiscountRedemption.discount_id)
        .outerjoin(Order, DiscountRedemption.order_id == Order.id)
        .where(
            DiscountRedemption.shop_id == shop.id,
            DiscountRedemption.status == "active",
            or_(
                DiscountRedemption.order_id.is_(None),
                func.lower(Order.order_status).notin_(["cancelled", "rejected"])
            ),
            or_(*token_filters)
        )
    )
    claimed_discount_ids = {str(did) for did in claimed_res.scalars().all()}

    cd_res = await db.execute(
        select(CustomerDiscountCode.discount_id).where(
            CustomerDiscountCode.shop_id == shop.id,
            CustomerDiscountCode.customer_identifier.in_(phone_variants),
            CustomerDiscountCode.is_redeemed == True
        )
    )
    claimed_discount_ids.update({str(did) for did in cd_res.scalars().all()})

    return {
        "exists": bool(customer),
        "id": str(customer.id) if customer else None,
        "name": (customer.name if customer else "") or "",
        "phone": (customer.mobile_number if customer else (f"+91{clean_phone}" if len(clean_phone) == 10 else phone)),
        "delivery_address": (customer.delivery_address if customer else "") or "",
        "used_discount_ids": list(claimed_discount_ids)
    }


@router.post("", response_model=OrderResponse)
async def create_manual_order(
    order_data: OrderCreate,
    shop = Depends(require_permission("orders", "write")),
    db: AsyncSession = Depends(get_db),
):
    """Manually create an order by merchant/staff in the merchant portal."""
    await check_orders_subscription(shop, db)
    service = OrderService(db)
    order = await service.create_order(shop.id, order_data)
    
    is_paid = (order_data.payment_status or "").lower() == "paid"
    if is_paid:
        order.payment_status = "paid"
        order.order_status = "PREPARING"
        # Only dispatches if payment_status == "paid"
        await service._send_order_status_whatsapp_notification(order)
    else:
        order.payment_status = "pending"
        order.order_status = "PAYMENT_PENDING"

        from datetime import datetime, timezone, timedelta
        order.payment_expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)

        # If customer phone is provided, send payment link notification
        if order.customer_phone:
            await service._send_order_accepted_payment_required_whatsapp_notification(order)
    
    await db.commit()
    await db.refresh(order)
    return OrderResponse.model_validate(order)





@router.post("/{order_id}/items", response_model=OrderResponse)
async def append_items_to_order(
    order_id: str,
    data: OrderAddItems,
    shop = Depends(require_permission("orders", "write")),
    db: AsyncSession = Depends(get_db),
):
    """Append additional menu items to an existing active order."""
    import uuid
    await check_orders_subscription(shop, db)
    service = OrderService(db)
    items_dicts = [it.model_dump() for it in data.items]
    order = await service.append_items_to_order(uuid.UUID(order_id), shop.id, items_dicts)
    await db.commit()
    await db.refresh(order)
    return OrderResponse.model_validate(order)


@router.put("/{order_id}/items/{item_id}/toggle-complete", response_model=OrderResponse)
async def toggle_item_completion(
    order_id: str,
    item_id: str,
    shop = Depends(require_permission("orders", "write")),
    db: AsyncSession = Depends(get_db),
):
    """Toggle individual item completed status (Served / Given vs New / Preparing)."""
    import uuid
    await check_orders_subscription(shop, db)
    service = OrderService(db)
    order = await service.toggle_order_item_completion(
        uuid.UUID(order_id),
        uuid.UUID(item_id),
        shop.id
    )
    await db.commit()
    await db.refresh(order)
    return OrderResponse.model_validate(order)


@router.put("/{order_id}/items/{item_id}/toggle-cancel", response_model=OrderResponse)
async def toggle_item_cancel(
    order_id: str,
    item_id: str,
    cancel_data: Optional[OrderItemCancel] = None,
    shop = Depends(require_permission("orders", "write")),
    db: AsyncSession = Depends(get_db),
):
    """Toggle individual item cancellation status (Cancelled vs Active), adjust order total, and save reason."""
    import uuid
    await check_orders_subscription(shop, db)
    service = OrderService(db)
    reason = cancel_data.reason if cancel_data else None
    order = await service.toggle_order_item_cancel(
        uuid.UUID(order_id),
        uuid.UUID(item_id),
        shop.id,
        reason=reason,
    )
    await db.commit()
    await db.refresh(order)
    return OrderResponse.model_validate(order)


@router.post("/{order_id}/items/{item_id}/replace", response_model=OrderResponse)
async def replace_order_item(
    order_id: str,
    item_id: str,
    replace_data: OrderItemReplace,
    shop = Depends(require_permission("orders", "write")),
    db: AsyncSession = Depends(get_db),
):
    """Atomically replace an order item with another item and recalculate totals."""
    import uuid
    await check_orders_subscription(shop, db)
    service = OrderService(db)
    order = await service.replace_order_item(
        uuid.UUID(order_id),
        uuid.UUID(item_id),
        shop.id,
        replace_data=replace_data,
    )
    await db.commit()
    await db.refresh(order)
    return OrderResponse.model_validate(order)


@router.post("/{order_id}/items/{item_id}/replace-preview")
async def replace_order_item_preview(
    order_id: str,
    item_id: str,
    replace_data: OrderItemReplace,
    shop = Depends(require_permission("orders", "read")),
    db: AsyncSession = Depends(get_db),
):
    """Preview the exact price difference, refund, or additional payment for replacing an item."""
    import uuid
    service = OrderService(db)
    preview = await service.preview_replace_order_item(
        uuid.UUID(order_id),
        uuid.UUID(item_id),
        shop.id,
        replace_data=replace_data,
    )
    return preview




