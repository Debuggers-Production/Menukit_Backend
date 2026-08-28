"""QR code generation service."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.qr_code import QRCode
from app.models.shop import Shop
from app.models.activity_log import ActivityLog
from app.core.config import get_settings
from app.core.exceptions import NotFoundException

settings = get_settings()


class QRService:
    """Handles QR code generation and management."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def generate_qr(self, shop_id: uuid.UUID, user_id: uuid.UUID) -> QRCode:
        """Generate or regenerate QR code for the shop."""
        # Check if QR already exists for the user
        result = await self.db.execute(select(QRCode).where(QRCode.user_id == user_id))
        existing_qr = result.scalar_one_or_none()

        qr_url = f"{settings.FRONTEND_URL}/shop/{shop_id}?type=qr"

        if existing_qr:
            existing_qr.qr_url = qr_url
            existing_qr.qr_image_url = None
            existing_qr.qr_svg_data = None
            qr_code = existing_qr
        else:
            qr_code = QRCode(
                user_id=user_id,
                qr_url=qr_url,
                qr_image_url=None,
                qr_svg_data=None,
            )
            self.db.add(qr_code)

        # Log activity
        activity = ActivityLog(
            user_id=user_id,
            action="qr_generate",
            details="Generated Shop QR Code",
        )
        self.db.add(activity)

        await self.db.commit()
        await self.db.refresh(qr_code)
        return qr_code

    async def get_qr(self, user_id: uuid.UUID, shop_id: uuid.UUID = None) -> QRCode:
        """Get QR code for the shop."""
        result = await self.db.execute(select(QRCode).where(QRCode.user_id == user_id))
        qr = result.scalar_one_or_none()
        if not qr:
            raise NotFoundException("QR code not found. Generate one first.")
        if shop_id and (not qr.qr_url or "/brand/" in qr.qr_url):
            qr.qr_url = f"{settings.FRONTEND_URL}/shop/{shop_id}?type=qr"
            self.db.add(qr)
            await self.db.commit()
            await self.db.refresh(qr)
        return qr

    async def update_qr_style(self, user_id: uuid.UUID, style_data) -> QRCode:
        """Update style preferences for the brand QR code."""
        result = await self.db.execute(select(QRCode).where(QRCode.user_id == user_id))
        qr = result.scalar_one_or_none()
        if not qr:
            raise NotFoundException("QR code not found. Generate one first.")

        qr.dot_type = style_data.dot_type
        qr.corners_square_type = style_data.corners_square_type
        qr.corners_dot_type = style_data.corners_dot_type
        qr.qr_color = style_data.qr_color
        qr.include_logo = style_data.include_logo

        self.db.add(qr)
        await self.db.commit()
        await self.db.refresh(qr)
        return qr
