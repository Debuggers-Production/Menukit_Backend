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


class FCMRegisterTokenRequest(BaseModel):
    token: str = Field(..., description="FCM device registration token")
    shop_id: Optional[UUID4] = Field(default=None, description="Associated Shop UUID if merchant/staff")
    customer_phone: Optional[str] = Field(default=None, description="Customer phone number if customer device")
    customer_id: Optional[UUID4] = Field(default=None, description="Customer UUID if authenticated customer")
    platform: Optional[str] = Field(default="web", description="web | android | ios")
    device_type: Optional[str] = Field(default="desktop", description="desktop | mobile | tablet")
    browser: Optional[str] = Field(default=None, description="chrome | safari | firefox | edge")
    user_agent: Optional[str] = Field(default=None, description="Client user agent string")


class FCMUnregisterTokenRequest(BaseModel):
    token: str = Field(..., description="FCM device token to unregister")


class FCMTestNotificationRequest(BaseModel):
    token: Optional[str] = Field(default=None, description="Direct FCM token to test")
    shop_id: Optional[UUID4] = Field(default=None, description="Test send to all active shop devices")
    customer_phone: Optional[str] = Field(default=None, description="Test send to customer phone devices")
    title: str = Field(default="Menukit Test Notification", description="Notification title")
    body: str = Field(default="FCM Push Notification is working smoothly!", description="Notification body")
    url: Optional[str] = Field(default="/orders", description="Target link when clicked")

