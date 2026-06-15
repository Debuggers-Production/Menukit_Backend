"""Membership schemas."""

import uuid
from datetime import datetime
from pydantic import BaseModel, Field, constr


class AddMemberRequest(BaseModel):
    name: str | None = Field(None, max_length=100)
    mobile_number: constr(min_length=10, max_length=15, pattern=r'^\+?[0-9]+$') # type: ignore


class MembershipAnalyticsResponse(BaseModel):
    total_members: int
    manually_added: int
    auto_registered: int


class MembershipEventRequest(BaseModel):
    event_type: str
    customer_id: uuid.UUID | None = None

class MemberResponse(BaseModel):
    id: uuid.UUID
    name: str | None = None
    mobile_number: str
    joined_at: datetime
