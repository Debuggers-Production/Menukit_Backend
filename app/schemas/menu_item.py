"""Menu item schemas."""

from typing import Optional, List
from decimal import Decimal
from pydantic import BaseModel


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


class MenuItemAddon(BaseModel):
    """Menu item addon."""
    name: str
    price: str


class MenuItemCreate(BaseModel):
    """Create a new menu item."""
    category_id: str
    name: str
    description: Optional[str] = None
    price: Decimal
    offer_price: Optional[Decimal] = None
    food_type: str = "veg"  # veg | non-veg | egg | drink
    allow_ice_preference: bool = False
    is_bestseller: bool = False
    is_highlighted: bool = False
    is_available: bool = True
    display_order: Optional[int] = 0
    variants: Optional[List[MenuItemVariant]] = []
    addons: Optional[List[MenuItemAddon]] = None


class MenuItemUpdate(BaseModel):
    """Update a menu item."""
    category_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[Decimal] = None
    offer_price: Optional[Decimal] = None
    food_type: Optional[str] = None
    allow_ice_preference: Optional[bool] = None
    is_bestseller: Optional[bool] = None
    is_highlighted: Optional[bool] = None
    is_available: Optional[bool] = None
    display_order: Optional[int] = None
    variants: Optional[List[MenuItemVariant]] = None
    addons: Optional[List[MenuItemAddon]] = None


class MenuItemReorder(BaseModel):
    """Reorder menu items."""
    order: List[dict]  # [{"id": "uuid", "display_order": 0}]


class MenuItemResponse(BaseModel):
    """Menu item response."""
    id: str
    category_id: str
    name: str
    description: Optional[str] = None
    price: str
    offer_price: Optional[str] = None
    food_type: str
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
    average_rating: Optional[float] = None
    review_count: int = 0
    created_at: str

    class Config:
        from_attributes = True
