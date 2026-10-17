"""Broadcast campaign schemas."""

from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, field_validator
from app.utils.media import resolve_image_url, strip_image_base_url


class AudienceCountRequest(BaseModel):
    target_audience: str = "all"  # 'all', 'new', 'min_visits'
    min_visits: Optional[int] = 2


class AudienceCountResponse(BaseModel):
    count: int
    target_audience: str
    min_visits: Optional[int] = None


class BroadcastTestSendRequest(BaseModel):
    phone_number: str
    message: str
    image_url: Optional[str] = None

    @field_validator("image_url", mode="before")
    @classmethod
    def resolve_test_image_url(cls, v):
        return resolve_image_url(v)


class BroadcastCampaignCreate(BaseModel):
    title: Optional[str] = None
    message: str
    image_url: Optional[str] = None
    target_audience: str = "all"
    min_visits: Optional[int] = 2
    scheduled_at: Optional[datetime] = None

    @field_validator("image_url", mode="before")
    @classmethod
    def strip_campaign_image_url(cls, v):
        return strip_image_base_url(v)



class BroadcastCampaignResponse(BaseModel):
    id: str
    shop_id: str
    title: str
    message: str
    image_url: Optional[str] = None
    target_audience: str
    min_visits: Optional[int] = None
    status: str
    scheduled_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    total_recipients: int
    sent_count: int
    failed_count: int
    created_at: Optional[datetime] = None

    @field_validator("image_url", mode="before")
    @classmethod
    def resolve_campaign_image_url(cls, v):
        return resolve_image_url(v)

    class Config:
        from_attributes = True


class BroadcastCampaignListResponse(BaseModel):
    items: List[BroadcastCampaignResponse]
    total: int
    page: int
    page_size: int
    has_more: bool

