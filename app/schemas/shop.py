"""Shop schemas."""

import uuid
from typing import Optional
from pydantic import BaseModel


class ShopCreate(BaseModel):
    """Create a new shop."""
    name: str
    description: Optional[str] = None
    welcome_message: Optional[str] = None
    phone: Optional[str] = None
    whatsapp: Optional[str] = None
    address: Optional[str] = None
    category: Optional[str] = None
    cuisine: Optional[str] = None
    city: Optional[str] = None
    area: Optional[str] = None
    opening_time: Optional[str] = None
    closing_time: Optional[str] = None


class ShopUpdate(BaseModel):
    """Update shop details."""
    name: Optional[str] = None
    description: Optional[str] = None
    welcome_message: Optional[str] = None
    logo_url: Optional[str] = None
    banner_url: Optional[str] = None
    phone: Optional[str] = None
    whatsapp: Optional[str] = None
    address: Optional[str] = None
    category: Optional[str] = None
    cuisine: Optional[str] = None
    city: Optional[str] = None
    area: Optional[str] = None
    opening_time: Optional[str] = None
    closing_time: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    google_review_link: Optional[str] = None
    review_widget_code: Optional[str] = None


class ShopSettingsUpdate(BaseModel):
    """Update shop settings."""
    currency: Optional[str] = None
    language: Optional[str] = None
    show_prices: Optional[bool] = None
    show_offers: Optional[bool] = None
    is_discoverable: Optional[bool] = None
    show_menus_in_discovery: Optional[bool] = None
    delivery_enabled: Optional[bool] = None
    base_delivery_charge: Optional[float] = None
    base_delivery_distance: Optional[float] = None
    extra_delivery_distance_step: Optional[float] = None
    extra_delivery_charge_per_step: Optional[float] = None
    takeaway_enabled: Optional[bool] = None
    dinein_enabled: Optional[bool] = None
    auto_accept_orders: Optional[bool] = None
    online_payments_enabled: Optional[bool] = None
    cashfree_app_id: Optional[str] = None
    cashfree_secret_key: Optional[str] = None
    cashfree_sandbox: Optional[bool] = None
    upi_id: Optional[str] = None


class ThemeSettingsUpdate(BaseModel):
    """Update theme settings."""
    theme: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    font_family: Optional[str] = None
    layout: Optional[str] = None
    banner_style: Optional[str] = None
    theme_scope: Optional[str] = None
    discount_card_style: Optional[str] = None
    menu_item_style: Optional[str] = None
    border_radius: Optional[str] = None


class ThemeSettingsResponse(BaseModel):
    """Theme settings response."""
    id: uuid.UUID
    theme: str
    primary_color: str
    secondary_color: str
    font_family: str
    layout: str
    banner_style: str
    theme_scope: str
    discount_card_style: str
    menu_item_style: str
    border_radius: str

    class Config:
        from_attributes = True


class ShopSettingsResponse(BaseModel):
    """Shop settings response."""
    id: uuid.UUID
    currency: str
    language: str
    show_prices: bool
    show_offers: bool
    is_discoverable: bool
    show_menus_in_discovery: bool
    delivery_enabled: bool
    base_delivery_charge: float = 0.0
    base_delivery_distance: float = 0.0
    extra_delivery_distance_step: float = 1.0
    extra_delivery_charge_per_step: float = 0.0
    takeaway_enabled: bool
    dinein_enabled: bool
    auto_accept_orders: bool
    cashfree_app_id: str
    cashfree_secret_key: str
    cashfree_sandbox: bool
    upi_id: Optional[str] = None
    online_payments_enabled: bool = True

    class Config:
        from_attributes = True


class ShopResponse(BaseModel):
    """Shop response."""
    id: str
    name: str
    slug: str
    description: Optional[str] = None
    welcome_message: Optional[str] = None
    logo_url: Optional[str] = None
    banner_url: Optional[str] = None
    phone: Optional[str] = None
    whatsapp: Optional[str] = None
    address: Optional[str] = None
    category: Optional[str] = None
    cuisine: Optional[str] = None
    city: Optional[str] = None
    area: Optional[str] = None
    opening_time: Optional[str] = None
    closing_time: Optional[str] = None
    is_active: bool
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    google_review_link: Optional[str] = None
    review_widget_code: Optional[str] = None
    settings: Optional[ShopSettingsResponse] = None
    theme: Optional[ThemeSettingsResponse] = None
    created_at: str

    class Config:
        from_attributes = True
