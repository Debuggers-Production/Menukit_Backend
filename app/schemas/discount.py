"""Discount schemas."""

from typing import Optional, List
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel


class DiscountCreate(BaseModel):
    """Create a new discount."""
    title: str
    description: Optional[str] = None
    discount_type: str = "percentage"  # "percentage" | "flat" | "bogo" | "combo"
    discount_value: Optional[Decimal] = None
    buy_quantity: Optional[int] = None
    get_quantity: Optional[int] = None
    reward_target_ids: Optional[List[str]] = None
    applies_to: str = "all"  # "all" | "category" | "items"
    target_ids: Optional[List[str]] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    available_days: Optional[List[str]] = None
    available_time_presets: Optional[List[str]] = None
    is_active: bool = True
    visibility_type: str = "everyone_unlock_members"


class DiscountUpdate(BaseModel):
    """Update a discount."""
    title: Optional[str] = None
    description: Optional[str] = None
    discount_type: Optional[str] = None
    discount_value: Optional[Decimal] = None
    buy_quantity: Optional[int] = None
    get_quantity: Optional[int] = None
    reward_target_ids: Optional[List[str]] = None
    applies_to: Optional[str] = None
    target_ids: Optional[List[str]] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    available_days: Optional[List[str]] = None
    available_time_presets: Optional[List[str]] = None
    is_active: Optional[bool] = None
    visibility_type: Optional[str] = None


class DiscountResponse(BaseModel):
    """Discount response."""
    id: str
    shop_id: str
    title: str
    description: Optional[str] = None
    discount_type: str
    discount_value: Optional[str] = None
    buy_quantity: Optional[int] = None
    get_quantity: Optional[int] = None
    reward_target_ids: Optional[List[str]] = None
    applies_to: str
    target_ids: Optional[List[str]] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    available_days: Optional[List[str]] = None
    available_time_presets: Optional[List[str]] = None
    is_active: bool
    visibility_type: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True
