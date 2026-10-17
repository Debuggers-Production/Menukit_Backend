"""Schemas for Scheme (Pandu) feature."""

from datetime import datetime
from decimal import Decimal
from typing import Optional, List, Any
from pydantic import BaseModel, Field, field_validator
from app.utils.media import resolve_image_url


class SchemeItemInfo(BaseModel):
    item_id: str
    name: str
    variant_name: Optional[str] = None
    quantity: int = 1
    price: float = 0.0
    image_url: Optional[str] = None

    @field_validator("image_url", mode="before")
    @classmethod
    def resolve_image_url(cls, v):
        return resolve_image_url(v)


class SchemeBase(BaseModel):
    title: str = Field(..., min_length=2, max_length=255)
    description: Optional[str] = None
    price: Decimal = Field(..., gt=0)
    frequency: str = Field(default="monthly")  # "monthly" | "weekly"
    term_duration: int = Field(default=12, ge=1)
    term_unit: str = Field(default="months")  # "months" | "weeks" | "years"
    max_members: Optional[int] = Field(default=None, ge=1)
    items: List[SchemeItemInfo] = Field(default_factory=list)
    show_on_public_menu: bool = True
    status: str = Field(default="active")  # "active" | "closed" | "completed"
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


class SchemeCreate(SchemeBase):
    pass


class SchemeUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    price: Optional[Decimal] = None
    frequency: Optional[str] = None
    term_duration: Optional[int] = None
    term_unit: Optional[str] = None
    max_members: Optional[int] = None
    items: Optional[List[SchemeItemInfo]] = None
    show_on_public_menu: Optional[bool] = None
    status: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


class SchemePaymentResponse(BaseModel):
    id: str
    scheme_id: str
    member_id: str
    installment_number: int
    installment_label: str
    amount: float
    status: str
    payment_method: str
    paid_at: datetime
    transaction_id: Optional[str] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class InstallmentScheduleItem(BaseModel):
    installment_number: int
    label: str  # e.g. "Month 1 (Oct 2026)"
    due_date: Optional[datetime] = None
    amount: float
    is_paid: bool
    paid_at: Optional[datetime] = None
    payment_method: Optional[str] = None
    payment_id: Optional[str] = None


class SchemeMemberResponse(BaseModel):
    id: str
    scheme_id: str
    shop_id: str
    customer_id: Optional[str] = None
    customer_name: str
    customer_phone: str
    customer_address: Optional[str] = None
    member_number: Optional[str] = None
    status: str
    joined_at: datetime
    total_installments: int
    paid_installments: int
    notes: Optional[str] = None
    payments: List[SchemePaymentResponse] = Field(default_factory=list)
    installment_schedule: List[InstallmentScheduleItem] = Field(default_factory=list)

    class Config:
        from_attributes = True


class SchemeMemberCreate(BaseModel):
    customer_name: str = Field(..., min_length=1, max_length=255)
    customer_phone: str = Field(..., min_length=7, max_length=20)
    customer_address: Optional[str] = None
    member_number: Optional[str] = None
    notes: Optional[str] = None
    initial_payment: bool = False
    payment_method: str = "cash"  # "cash" | "upi" | "card" | "online"
    transaction_id: Optional[str] = None


class RecordPaymentRequest(BaseModel):
    installment_number: int = Field(..., ge=1)
    installment_label: Optional[str] = None
    amount: Optional[Decimal] = None
    payment_method: str = "cash"  # "cash" | "upi" | "card" | "online"
    transaction_id: Optional[str] = None
    notes: Optional[str] = None


class SchemeStats(BaseModel):
    total_members: int = 0
    paid_this_cycle_count: int = 0
    pending_this_cycle_count: int = 0
    total_collected: float = 0.0
    completion_rate_percent: float = 0.0


class SchemeResponse(BaseModel):
    id: str
    shop_id: str
    title: str
    description: Optional[str] = None
    price: float
    frequency: str
    term_duration: int
    term_unit: str
    max_members: Optional[int] = None
    items: List[SchemeItemInfo] = Field(default_factory=list)
    show_on_public_menu: bool = True
    status: str
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    stats: Optional[SchemeStats] = None

    class Config:
        from_attributes = True


class PublicSchemeResponse(BaseModel):
    id: str
    shop_id: str
    title: str
    description: Optional[str] = None
    price: float
    frequency: str
    term_duration: int
    term_unit: str
    max_members: Optional[int] = None
    total_members: int = 0
    remaining_spots: Optional[int] = None
    items: List[SchemeItemInfo] = Field(default_factory=list)
    status: str


class PublicSchemeJoinRequest(BaseModel):
    customer_name: str = Field(..., min_length=1, max_length=255)
    customer_phone: str = Field(..., min_length=7, max_length=20)
    customer_address: Optional[str] = None
    notes: Optional[str] = None


class CustomerSchemePassResponse(BaseModel):
    member_id: str
    scheme_id: str
    scheme_title: str
    price: float
    frequency: str
    term_duration: int
    term_unit: str
    customer_name: str
    customer_phone: str
    member_number: Optional[str] = None
    status: str
    joined_at: datetime
    total_installments: int
    paid_installments: int
    remaining_installments: int
    items: List[SchemeItemInfo] = Field(default_factory=list)
    payments: List[SchemePaymentResponse] = Field(default_factory=list)
    installment_schedule: List[InstallmentScheduleItem] = Field(default_factory=list)


class SchemePaymentInitiateRequest(BaseModel):
    customer_name: str = Field(..., min_length=1, max_length=255)
    customer_phone: str = Field(..., min_length=7, max_length=20)
    customer_address: Optional[str] = None


class SchemePaymentInitiateResponse(BaseModel):
    razorpay_order_id: str
    razorpay_key: str
    base_total: float
    platform_fee: float
    pg_fee: float
    gst_on_fee: float
    grand_total: float
    amount: int
    currency: str = "INR"
    mock_mode: bool = False


class SchemePaymentVerifyRequest(BaseModel):
    customer_name: str = Field(..., min_length=1, max_length=255)
    customer_phone: str = Field(..., min_length=7, max_length=20)
    customer_address: Optional[str] = None
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
