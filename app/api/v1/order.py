"""Order API endpoints for merchants."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.database.session import get_db
from app.core.deps import get_current_user
from app.schemas.order import OrderResponse, OrderStatusUpdate, PaymentStatusUpdate
from app.services.order_service import OrderService
from app.models.user import User

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.get("", response_model=List[OrderResponse])
async def list_orders(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all orders for the merchant's restaurant."""
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
    service = OrderService(db)
    order = await service.update_payment_status(uuid.UUID(order_id), data.payment_status, user.id)
    await db.commit()
    return OrderResponse.model_validate(order)
