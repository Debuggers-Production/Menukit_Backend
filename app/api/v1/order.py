"""Order API endpoints for merchants."""

import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.database.session import get_db
from app.core.deps import get_current_user
from app.schemas.order import OrderResponse, OrderStatusUpdate, PaymentStatusUpdate
from app.services.order_service import OrderService
from app.models.user import User

router = APIRouter(prefix="/orders", tags=["Orders"])


async def check_orders_subscription(user_id: uuid.UUID, db: AsyncSession):
    """Backend subscription verification for orders management endpoints."""
    from app.services.shop_service import ShopService
    from app.services.subscription_helper import get_shop_subscription_permissions
    from fastapi import HTTPException
    shop = await ShopService(db).get_shop_by_user(user_id)
    if shop:
        perms = await get_shop_subscription_permissions(shop.id, db)
        if perms["is_expired"] or not perms["online_orders"]:
            raise HTTPException(
                status_code=403,
                detail="Subscription required: Orders management is locked due to an inactive or missing online-orders module. Please purchase the Online Visibility & Orders Accept module."
            )


@router.get("", response_model=List[OrderResponse])
async def list_orders(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all orders for the merchant's restaurant."""
    import uuid
    await check_orders_subscription(user.id, db)
    service = OrderService(db)
    orders = await service.get_orders_by_user(user.id)
    return [OrderResponse.model_validate(o) for o in orders]


@router.put("/{order_id}/status", response_model=OrderResponse)
async def update_order_status(
    order_id: str,
    status_data: OrderStatusUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update order status (e.g. accept, complete, rejected, cancelled)."""
    import uuid
    await check_orders_subscription(user.id, db)
    service = OrderService(db)
    order = await service.update_order_status(uuid.UUID(order_id), status_data.status, user.id)
    await db.commit()
    return OrderResponse.model_validate(order)


@router.put("/{order_id}/payment-status", response_model=OrderResponse)
async def update_order_payment_status(
    order_id: str,
    data: PaymentStatusUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update payment status of an order (e.g. mark as paid or pending)."""
    import uuid
    await check_orders_subscription(user.id, db)
    service = OrderService(db)
    order = await service.update_payment_status(uuid.UUID(order_id), data.payment_status, user.id)
    await db.commit()
    return OrderResponse.model_validate(order)
