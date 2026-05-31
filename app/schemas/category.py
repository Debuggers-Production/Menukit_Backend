"""Category schemas."""

from typing import Optional, List
from pydantic import BaseModel


class CategoryCreate(BaseModel):
    """Create a new category."""
    name: str
    image_url: Optional[str] = None
    display_order: Optional[int] = 0


class CategoryUpdate(BaseModel):
    """Update a category."""
    name: Optional[str] = None
    image_url: Optional[str] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


class CategoryReorder(BaseModel):
    """Reorder categories."""
    order: List[dict]  # [{"id": "uuid", "display_order": 0}]


class CategoryResponse(BaseModel):
    """Category response."""
    id: str
    name: str
    image_url: Optional[str] = None
    display_order: int
    is_active: bool
    item_count: Optional[int] = 0
    created_at: str

    class Config:
        from_attributes = True
