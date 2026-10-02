"""Menu item schemas."""

from typing import Optional, List
from decimal import Decimal
from pydantic import BaseModel, model_validator


class MenuImageResponse(BaseModel):
    """Menu image response."""
    id: str
    image_url: str
    thumbnail_url: Optional[str] = None
    is_primary: bool
    display_order: int

    class Config:
        from_attributes = True


class MenuItemVariant(BaseModel):
    """Menu item variant."""
    name: str
    price: str
    offer_price: Optional[str] = None
    wholesale_price: Optional[str] = None
    other_price: Optional[str] = None
    online_price: Optional[str] = None
    online_offer_price: Optional[str] = None
    multiplier: Optional[int] = 1
    wholesale_multiplier: Optional[int] = 1
    other_multiplier: Optional[int] = 1
    is_public_visible: Optional[bool] = True


class MenuItemAddon(BaseModel):
    """Menu item addon."""
    name: str
    price: str


class MenuItemCreate(BaseModel):
    """Create a new menu item."""
    category_id: str
    name: str
    serial_number: Optional[str] = None
    multiplier: Optional[int] = 1
    wholesale_multiplier: Optional[int] = 1
    other_multiplier: Optional[int] = 1
    description: Optional[str] = None
    price: Decimal
    offer_price: Optional[Decimal] = None
    wholesale_price: Optional[Decimal] = None
    other_price: Optional[Decimal] = None
    online_price: Optional[Decimal] = None
    online_offer_price: Optional[Decimal] = None
    food_types: List[str] = ["veg"]  # veg | non-veg | egg | drink
    allow_ice_preference: bool = False
    is_bestseller: bool = False
    is_highlighted: bool = False
    is_available: bool = True
    display_order: Optional[int] = 0
    variants: Optional[List[MenuItemVariant]] = []
    addons: Optional[List[MenuItemAddon]] = None
    available_days: Optional[List[str]] = []
    available_time_presets: Optional[List[str]] = []
    custom_time_from: Optional[str] = None
    custom_time_to: Optional[str] = None

    @model_validator(mode="after")
    def validate_offer_prices(self):
        if self.offer_price is not None and self.price is not None:
            if self.offer_price >= self.price:
                raise ValueError(f"Offer price ({self.offer_price}) must always be less than regular price ({self.price}).")

        eff_online = self.online_price if self.online_price is not None else self.price
        if self.online_offer_price is not None and eff_online is not None:
            if self.online_offer_price >= eff_online:
                raise ValueError(f"Online offer price ({self.online_offer_price}) must always be less than online price ({eff_online}).")

        if self.variants:
            for v in self.variants:
                try:
                    vp = Decimal(str(v.price))
                    if v.offer_price:
                        vop = Decimal(str(v.offer_price))
                        if vop >= vp:
                            raise ValueError(f"Variant '{v.name}': Offer price ({vop}) must always be less than regular price ({vp}).")
                    v_eff_online = Decimal(str(v.online_price)) if v.online_price else vp
                    if v.online_offer_price:
                        voop = Decimal(str(v.online_offer_price))
                        if voop >= v_eff_online:
                            raise ValueError(f"Variant '{v.name}': Online offer price ({voop}) must always be less than online price ({v_eff_online}).")
                except (ValueError, TypeError) as e:
                    if "must always be less" in str(e):
                        raise e
        return self


class MenuItemUpdate(BaseModel):
    """Update a menu item."""
    category_id: Optional[str] = None
    name: Optional[str] = None
    serial_number: Optional[str] = None
    multiplier: Optional[int] = None
    wholesale_multiplier: Optional[int] = None
    other_multiplier: Optional[int] = None
    description: Optional[str] = None
    price: Optional[Decimal] = None
    offer_price: Optional[Decimal] = None
    wholesale_price: Optional[Decimal] = None
    other_price: Optional[Decimal] = None
    online_price: Optional[Decimal] = None
    online_offer_price: Optional[Decimal] = None
    food_types: Optional[List[str]] = None
    allow_ice_preference: Optional[bool] = None
    is_bestseller: Optional[bool] = None
    is_highlighted: Optional[bool] = None
    is_available: Optional[bool] = None
    display_order: Optional[int] = None
    variants: Optional[List[MenuItemVariant]] = None
    addons: Optional[List[MenuItemAddon]] = None
    available_days: Optional[List[str]] = None
    available_time_presets: Optional[List[str]] = None
    custom_time_from: Optional[str] = None
    custom_time_to: Optional[str] = None

    @model_validator(mode="after")
    def validate_offer_prices(self):
        if self.offer_price is not None and self.price is not None:
            if self.offer_price >= self.price:
                raise ValueError(f"Offer price ({self.offer_price}) must always be less than regular price ({self.price}).")

        eff_online = self.online_price if self.online_price is not None else self.price
        if self.online_offer_price is not None and eff_online is not None:
            if self.online_offer_price >= eff_online:
                raise ValueError(f"Online offer price ({self.online_offer_price}) must always be less than online price ({eff_online}).")

        if self.variants:
            for v in self.variants:
                try:
                    vp = Decimal(str(v.price))
                    if v.offer_price:
                        vop = Decimal(str(v.offer_price))
                        if vop >= vp:
                            raise ValueError(f"Variant '{v.name}': Offer price ({vop}) must always be less than regular price ({vp}).")
                    v_eff_online = Decimal(str(v.online_price)) if v.online_price else vp
                    if v.online_offer_price:
                        voop = Decimal(str(v.online_offer_price))
                        if voop >= v_eff_online:
                            raise ValueError(f"Variant '{v.name}': Online offer price ({voop}) must always be less than online price ({v_eff_online}).")
                except (ValueError, TypeError) as e:
                    if "must always be less" in str(e):
                        raise e
        return self


class MenuItemReorder(BaseModel):
    """Reorder menu items."""
    order: List[dict]  # [{"id": "uuid", "display_order": 0}]


class MenuItemResponse(BaseModel):
    """Menu item response."""
    id: str
    category_id: str
    name: str
    serial_number: Optional[str] = None
    multiplier: Optional[int] = 1
    wholesale_multiplier: Optional[int] = 1
    other_multiplier: Optional[int] = 1
    description: Optional[str] = None
    price: str
    offer_price: Optional[str] = None
    wholesale_price: Optional[str] = None
    other_price: Optional[str] = None
    online_price: Optional[str] = None
    online_offer_price: Optional[str] = None
    food_types: List[str]
    allow_ice_preference: bool
    is_bestseller: bool
    is_highlighted: bool
    is_available: bool
    display_order: int
    image_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    images: List[MenuImageResponse] = []
    variants: Optional[List[MenuItemVariant]] = []
    addons: Optional[List[MenuItemAddon]] = []
    available_days: Optional[List[str]] = []
    available_time_presets: Optional[List[str]] = []
    custom_time_from: Optional[str] = None
    custom_time_to: Optional[str] = None
    average_rating: Optional[float] = None
    review_count: int = 0
    created_at: str

    class Config:
        from_attributes = True
