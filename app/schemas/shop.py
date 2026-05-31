"""Shop schemas."""

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
    opening_time: Optional[str] = None
    closing_time: Optional[str] = None


class ShopSettingsUpdate(BaseModel):
    """Update shop settings."""
    currency: Optional[str] = None
    language: Optional[str] = None
    show_prices: Optional[bool] = None
    show_offers: Optional[bool] = None


class ThemeSettingsUpdate(BaseModel):
    """Update theme settings."""
    theme: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    font_family: Optional[str] = None
    layout: Optional[str] = None
    banner_style: Optional[str] = None


class ThemeSettingsResponse(BaseModel):
    """Theme settings response."""
    id: str
    theme: str
    primary_color: str
    secondary_color: str
    font_family: str
    layout: str
    banner_style: str

    class Config:
        from_attributes = True


class ShopSettingsResponse(BaseModel):
    """Shop settings response."""
    id: str
    currency: str
    language: str
    show_prices: bool
    show_offers: bool

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
    opening_time: Optional[str] = None
    closing_time: Optional[str] = None
    is_active: bool
    settings: Optional[ShopSettingsResponse] = None
    theme: Optional[ThemeSettingsResponse] = None
    created_at: str

    class Config:
        from_attributes = True
