"""Order API endpoints for merchants."""

import uuid
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from app.database.session import get_db
from app.core.deps import get_current_user, require_permission
from app.schemas.order import OrderResponse, OrderStatusUpdate, PaymentStatusUpdate
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
    shop = Depends(require_permission("orders", "read")),
    db: AsyncSession = Depends(get_db),
):
    """Get accurate shop-wide counts for order status tabs."""
    await check_orders_subscription(shop, db)
    service = OrderService(db)
    counts = await service.get_status_counts(shop.id)
    return counts


@router.get("", response_model=List[OrderResponse])
async def list_orders(
    response: Response,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query("all"),
    type_filter: Optional[str] = Query("all"),
    search: Optional[str] = Query(None),
    shop = Depends(require_permission("orders", "read")),
    db: AsyncSession = Depends(get_db),
):
    """List all orders for the merchant's restaurant with backend SQL search, filters, and pagination."""
    await check_orders_subscription(shop, db)
    service = OrderService(db)
    orders, total_count, has_more = await service.get_shop_orders(
        shop.id,
        skip=skip,
        limit=limit,
        status_filter=status_filter,
        type_filter=type_filter,
        search=search
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
    """Update order payment status."""
    import uuid
    await check_orders_subscription(shop, db)
    service = OrderService(db)
    order = await service.update_payment_status(
        uuid.UUID(order_id), 
        payment_data.payment_status, 
        shop.id
    )
    await db.commit()
    return OrderResponse.model_validate(order)


from app.schemas.order import OrderCreate, OrderAddItems

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
    # Automatically accept manual orders created by merchant
    order.order_status = "accepted"
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


