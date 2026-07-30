import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class QRCodeResponse(BaseModel):
    """QR code response."""
    id: uuid.UUID
    shop_id: uuid.UUID
    qr_url: str
    qr_image_url: Optional[str] = None
    qr_svg_data: Optional[str] = None
    dot_type: str = "dots"
    corners_square_type: str = "rounded"
    corners_dot_type: str = "dot"
    qr_color: str = "#1A1515"
    include_logo: bool = True
    created_at: datetime

    class Config:
        from_attributes = True


class QRCodeStyleUpdate(BaseModel):
    """QR code style update schema."""
    dot_type: str
    corners_square_type: str
    corners_dot_type: str
    qr_color: str
    include_logo: bool
