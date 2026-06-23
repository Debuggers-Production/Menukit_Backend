from pydantic import BaseModel, UUID4, Field
from datetime import datetime
from typing import Optional

class NotificationResponse(BaseModel):
    id: UUID4
    shop_id: UUID4
    type: str
    title: str
    message: str
    metadata_json: Optional[str] = None
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True

class MarkReadRequest(BaseModel):
    notification_ids: Optional[list[UUID4]] = Field(default=None, description="List of IDs to mark read. If empty, mark all as read.")
