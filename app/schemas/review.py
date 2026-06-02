"""Review schemas."""

from typing import Optional, List
from pydantic import BaseModel, Field, field_validator


class ReviewCreate(BaseModel):
    """Submit a new review."""
    rating: int = Field(..., ge=1, le=5, description="Star rating from 1 to 5")
    reviewer_name: Optional[str] = Field(None, max_length=100)
    comment: Optional[str] = Field(None, max_length=1000)

    @field_validator("reviewer_name", mode="before")
    @classmethod
    def clean_name(cls, v):
        if v:
            v = v.strip()
            return v if v else None
        return None

    @field_validator("comment", mode="before")
    @classmethod
    def clean_comment(cls, v):
        if v:
            v = v.strip()
            return v if v else None
        return None


class ReviewResponse(BaseModel):
    """Single review response."""
    id: str
    menu_item_id: str
    reviewer_name: Optional[str] = None
    rating: int
    comment: Optional[str] = None
    created_at: str

    class Config:
        from_attributes = True


class ReviewSummary(BaseModel):
    """Aggregated review summary for a menu item."""
    average_rating: float
    total_reviews: int
    rating_distribution: dict  # {1: 0, 2: 1, 3: 3, 4: 5, 5: 10}
    reviews: List[ReviewResponse] = []
