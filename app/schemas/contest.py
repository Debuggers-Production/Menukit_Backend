"""Contest schemas."""

from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel


class ContestCreate(BaseModel):
    title: str
    description: Optional[str] = None
    reward_type: str = "discount"  # "instant_cashback" | "free_food" | "discount" | "offer"
    reward_value: Optional[str] = None
    contest_type: str = "drawing"  # "drawing" | "kavithai"
    applies_to: str = "all"  # "all" | "items"
    target_ids: Optional[List[str]] = None
    ranking_criterion: str = "likes"  # "likes" | "comments" | "shares" | "all"
    min_participants: Optional[int] = 1
    min_likes: Optional[int] = 1
    min_comments: Optional[int] = 0
    min_shares: Optional[int] = 0


class ContestResponse(BaseModel):
    id: str
    shop_id: str
    title: str
    description: Optional[str] = None
    reward_type: str
    reward_value: Optional[str] = None
    contest_type: str
    applies_to: str
    target_ids: Optional[List[str]] = None
    status: str
    ends_at: datetime
    ranking_criterion: str = "likes"
    min_participants: int = 1
    min_likes: int = 1
    min_comments: int = 0
    min_shares: int = 0
    total_reserved_participants: int = 0
    cancel_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ContestParticipationCreate(BaseModel):
    contest_id: str
    content_type: str


class ContestParticipationSubmit(BaseModel):
    text_content: Optional[str] = None
    media_url: Optional[str] = None


class ContestParticipationResponse(BaseModel):
    id: str
    contest_id: str
    customer_id: str
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    content_type: str
    text_content: Optional[str] = None
    media_url: Optional[str] = None
    likes_count: int
    comments_count: int = 0
    shares_count: int = 0
    time_remaining_seconds: int
    is_timer_running: bool
    timer_last_updated_at: Optional[datetime] = None
    is_submitted: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ContestCreditResponse(BaseModel):
    customer_id: str
    credits: float

    class Config:
        from_attributes = True


class ContestPayRequest(BaseModel):
    mobile_number: str
    shop_id: str


class ContestVerifyRequest(BaseModel):
    link_id: str
    mobile_number: str


class ContestCommentCreate(BaseModel):
    text: str


class ContestCommentResponse(BaseModel):
    id: str
    participation_id: str
    customer_id: str
    customer_name: Optional[str] = None
    text: str
    likes_count: int = 0
    is_liked: Optional[bool] = False
    created_at: datetime

    class Config:
        from_attributes = True
