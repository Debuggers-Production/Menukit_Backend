"""Category schemas."""

from typing import Optional, List
from pydantic import BaseModel, field_validator
from app.utils.media import resolve_image_url, strip_image_base_url


class CategoryCreate(BaseModel):
    """Create a new category."""
    name: str
    image_url: Optional[str] = None
    display_order: Optional[int] = 0

    @field_validator("image_url", mode="before")
    @classmethod
    def strip_image_url(cls, v):
        return strip_image_base_url(v)


class CategoryUpdate(BaseModel):
    """Update a category."""
    name: Optional[str] = None
    image_url: Optional[str] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None

    @field_validator("image_url", mode="before")
    @classmethod
    def strip_image_url(cls, v):
        return strip_image_base_url(v)


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

    @field_validator("image_url", mode="before")
    @classmethod
    def resolve_image_url(cls, v):
        return resolve_image_url(v)

    class Config:
        from_attributes = True
