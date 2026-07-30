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

    async def generate_qr(self, user_id: uuid.UUID) -> QRCode:
        """Generate or regenerate QR code for user's shop."""
        result = await self.db.execute(select(Shop).where(Shop.user_id == user_id))
        shop = result.scalar_one_or_none()
        if not shop:
            raise NotFoundException("Shop not found. Create a shop first.")

        qr_url = f"{settings.FRONTEND_URL}/shop/{shop.id}"

        # Check if QR already exists
        result = await self.db.execute(select(QRCode).where(QRCode.shop_id == shop.id))
        existing_qr = result.scalar_one_or_none()

        if existing_qr:
            existing_qr.qr_url = qr_url
            existing_qr.qr_image_url = None
            existing_qr.qr_svg_data = None
            qr_code = existing_qr
        else:
            qr_code = QRCode(
                shop_id=shop.id,
                qr_url=qr_url,
                qr_image_url=None,
                qr_svg_data=None,
            )
            self.db.add(qr_code)

        # Log activity
        activity = ActivityLog(
            user_id=user_id,
            action="qr_generate",
            details=f"Generated QR code for {shop.name}",
        )
        self.db.add(activity)

        await self.db.commit()
        await self.db.refresh(qr_code)
        return qr_code

    async def get_qr(self, user_id: uuid.UUID) -> QRCode:
        """Get QR code for user's shop."""
        result = await self.db.execute(select(Shop).where(Shop.user_id == user_id))
        shop = result.scalar_one_or_none()
        if not shop:
            raise NotFoundException("Shop not found")

        result = await self.db.execute(select(QRCode).where(QRCode.shop_id == shop.id))
        qr = result.scalar_one_or_none()
        if not qr:
            raise NotFoundException("QR code not found. Generate one first.")

        return qr

    async def update_qr_style(self, user_id: uuid.UUID, style_data) -> QRCode:
        """Update style preferences for user's shop's QR code."""
        result = await self.db.execute(select(Shop).where(Shop.user_id == user_id))
        shop = result.scalar_one_or_none()
        if not shop:
            raise NotFoundException("Shop not found")

        result = await self.db.execute(select(QRCode).where(QRCode.shop_id == shop.id))
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
