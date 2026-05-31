"""Common schemas used across the application."""

from typing import Any, Generic, List, Optional, TypeVar
from pydantic import BaseModel

T = TypeVar("T")


class MessageResponse(BaseModel):
    """Simple message response."""
    message: str


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated response wrapper."""
    items: List[T]
    total: int
    page: int
    page_size: int
    total_pages: int


class ErrorResponse(BaseModel):
    """Error response."""
    detail: str
    error_code: Optional[str] = None
