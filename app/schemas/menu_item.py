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


class MenuItemCreate(BaseModel):
    """Create a new menu item."""
    category_id: str
    name: str
    description: Optional[str] = None
    price: Decimal
    offer_price: Optional[Decimal] = None
    food_type: str = "veg"  # veg | non-veg
    is_bestseller: bool = False
    is_highlighted: bool = False
    is_available: bool = True
    display_order: Optional[int] = 0


class MenuItemUpdate(BaseModel):
    """Update a menu item."""
    category_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[Decimal] = None
    offer_price: Optional[Decimal] = None
    food_type: Optional[str] = None
    is_bestseller: Optional[bool] = None
    is_highlighted: Optional[bool] = None
    is_available: Optional[bool] = None
    display_order: Optional[int] = None


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
    is_bestseller: bool
    is_highlighted: bool
    is_available: bool
    display_order: int
    image_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    images: List[MenuImageResponse] = []
    created_at: str

    class Config:
        from_attributes = True
