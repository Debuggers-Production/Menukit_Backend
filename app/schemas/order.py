"""Order schemas."""

import uuid
from typing import List, Optional
from pydantic import BaseModel, ConfigDict
from datetime import datetime


class OrderItemBase(BaseModel):
    menu_item_id: uuid.UUID
    name: str
    quantity: int
    price: float
    variant_info: Optional[dict] = None
    addons_info: Optional[List[dict]] = None


class OrderItemCreate(OrderItemBase):
    pass


class OrderAddItems(BaseModel):
    items: List[OrderItemCreate]


class OrderItemResponse(OrderItemBase):
    id: uuid.UUID
    order_id: uuid.UUID

    model_config = ConfigDict(from_attributes=True)


class OrderBase(BaseModel):
    customer_name: Optional[str] = "Walk-in"
    customer_phone: Optional[str] = ""
    order_type: str  # 'delivery', 'dine_in', 'takeaway'
    table_number: Optional[str] = None
    delivery_address: Optional[str] = None
    payment_method: str  # 'cash', 'online'
    total_amount: float


class OrderCreate(OrderBase):
    items: List[OrderItemCreate]


class OrderResponse(OrderBase):
    id: uuid.UUID
    shop_id: uuid.UUID
    order_status: str
    payment_status: str
    cashfree_order_id: Optional[str] = None
    payment_session_id: Optional[str] = None
    razorpay_order_id: Optional[str] = None
    settlement_status: Optional[str] = None
    settled_at: Optional[datetime] = None
    refund_id: Optional[str] = None
    cancellation_reason: Optional[str] = None
    payment_expires_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    items: List[OrderItemResponse] = []

    model_config = ConfigDict(from_attributes=True)


class OrderStatusUpdate(BaseModel):
    status: str  # 'pending', 'accepted', 'rejected', 'completed', 'cancelled'
    cancellation_reason: Optional[str] = None


class PaymentStatusUpdate(BaseModel):
    payment_status: str  # 'pending', 'paid', 'failed', 'refunded'
