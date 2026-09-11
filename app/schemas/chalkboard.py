"""Chalkboard schemas."""

import uuid
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


class ChalkboardUpdate(BaseModel):
    """Update chalkboard settings."""
    is_enabled: Optional[bool] = None
    title: Optional[str] = Field(None, max_length=50)
    message: Optional[str] = Field(None, max_length=250)


class ChalkboardResponse(BaseModel):
    """Chalkboard response."""
    id: uuid.UUID
    shop_id: uuid.UUID
    is_enabled: bool = True
    title: Optional[str] = None
    message: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
