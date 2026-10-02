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
    applied_discount_id: Optional[uuid.UUID] = None
    is_completed: bool = False
    is_cancelled: bool = False
    cancellation_reason: Optional[str] = None


class OrderItemCreate(OrderItemBase):
    pass


class OrderAddItems(BaseModel):
    items: List[OrderItemCreate]


class OrderItemCancel(BaseModel):
    reason: Optional[str] = "Cancelled by staff"


class OrderItemReplace(BaseModel):
    new_menu_item_id: uuid.UUID
    name: str
    quantity: int = 1
    price: float
    variant_info: Optional[dict] = None
    addons_info: Optional[List[dict]] = None
    reason: Optional[str] = "Customer requested item replacement"


class OrderItemResponse(OrderItemBase):
    id: uuid.UUID
    order_id: uuid.UUID
    is_completed: bool = False
    is_cancelled: bool = False
    cancellation_reason: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)




class OrderBase(BaseModel):
    customer_name: Optional[str] = "Walk-in"
    customer_phone: Optional[str] = ""
    order_type: str  # 'delivery', 'dine_in', 'takeaway'
    table_number: Optional[str] = None
    delivery_address: Optional[str] = None
    payment_method: str  # 'cash', 'online', 'upi', 'card', 'other', 'split'
    payment_status: Optional[str] = "pending"
    split_payments: Optional[List[dict]] = None
    price_tier: Optional[str] = "retail"  # 'retail', 'wholesale', 'other'
    total_amount: float
    applied_discount_ids: Optional[List[uuid.UUID]] = None
    applied_discount_codes: Optional[List[str]] = None



class OrderCreate(OrderBase):
    items: List[OrderItemCreate]


class OrderResponse(OrderBase):
    id: uuid.UUID
    shop_id: uuid.UUID
    order_status: str
    payment_status: str
    daily_order_number: Optional[int] = None
    cashfree_order_id: Optional[str] = None
    payment_session_id: Optional[str] = None
    razorpay_order_id: Optional[str] = None
    split_payments: Optional[List[dict]] = None
    price_tier: Optional[str] = "retail"
    applied_discount_ids: Optional[List[uuid.UUID]] = None
    applied_discount_codes: Optional[List[str]] = None
    settlement_status: Optional[str] = None
    settled_at: Optional[datetime] = None
    refund_id: Optional[str] = None
    cancellation_reason: Optional[str] = None
    payment_expires_at: Optional[datetime] = None
    whatsapp_sent: Optional[bool] = False
    created_at: datetime
    updated_at: datetime
    items: List[OrderItemResponse] = []

    model_config = ConfigDict(from_attributes=True)


class OrderStatusUpdate(BaseModel):
    status: str  # 'pending', 'accepted', 'rejected', 'completed', 'cancelled'
    cancellation_reason: Optional[str] = None


class PaymentStatusUpdate(BaseModel):
    payment_status: str  # 'pending', 'paid', 'failed', 'refunded'
