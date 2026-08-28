"""Employee schemas."""

from pydantic import BaseModel, EmailStr
from typing import Dict, List, Optional


class EmployeeCreate(BaseModel):
    """Schema for inviting a new employee."""
    email: EmailStr
    permissions: Dict[str, List[str]]


class EmployeeUpdate(BaseModel):
    """Schema for updating an employee's permissions."""
    permissions: Dict[str, List[str]]


class EmployeeResponse(BaseModel):
    """Employee response schema."""
    id: str
    shop_id: str
    user_id: Optional[str] = None
    email: str
    status: str
    permissions: Dict[str, List[str]]
    created_at: str

    class Config:
        from_attributes = True
