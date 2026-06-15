"""Customer schemas."""

import uuid
from datetime import datetime
from pydantic import BaseModel, Field, constr


class MobileVerifyRequest(BaseModel):
    mobile_number: constr(min_length=10, max_length=15, pattern=r'^\+?[0-9]+$') # type: ignore


class OTPVerifyRequest(BaseModel):
    mobile_number: constr(min_length=10, max_length=15, pattern=r'^\+?[0-9]+$') # type: ignore
    code: constr(min_length=6, max_length=6) # type: ignore
    shop_id: uuid.UUID | None = None


class OTPVerifyResponse(BaseModel):
    is_global_customer: bool
    is_member: bool
    is_strict_member: bool = False
    customer_name: str | None = None
    access_token: str | None = None


class CustomerRegisterRequest(BaseModel):
    mobile_number: constr(min_length=10, max_length=15, pattern=r'^\+?[0-9]+$') # type: ignore
    name: str = Field(..., min_length=2, max_length=100)
    shop_id: uuid.UUID | None = None
    otp_code: str | None = None # Required if registering directly without session


class CustomerResponse(BaseModel):
    id: uuid.UUID
    name: str | None
    mobile_number: str
    created_at: datetime

    class Config:
        from_attributes = True
