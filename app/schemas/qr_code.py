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
    created_at: datetime

    class Config:
        from_attributes = True
