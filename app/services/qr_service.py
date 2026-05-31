"""QR code generation service."""

import io
import uuid
import base64

import qrcode
import qrcode.image.svg
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

    def _generate_qr_png(self, url: str) -> bytes:
        """Generate QR code as PNG bytes."""
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )
        qr.add_data(url)
        qr.make(fit=True)

        img = qr.make_image(fill_color="#1e293b", back_color="white")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return buffer.getvalue()

    def _generate_qr_svg(self, url: str) -> str:
        """Generate QR code as SVG string."""
        factory = qrcode.image.svg.SvgPathImage
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4,
            image_factory=factory,
        )
        qr.add_data(url)
        qr.make(fit=True)

        img = qr.make_image()
        buffer = io.BytesIO()
        img.save(buffer)
        return buffer.getvalue().decode("utf-8")

    async def generate_qr(self, user_id: uuid.UUID) -> QRCode:
        """Generate or regenerate QR code for user's shop."""
        result = await self.db.execute(select(Shop).where(Shop.user_id == user_id))
        shop = result.scalar_one_or_none()
        if not shop:
            raise NotFoundException("Shop not found. Create a shop first.")

        qr_url = f"{settings.FRONTEND_URL}/shop/{shop.id}"

        # Generate PNG and SVG
        png_bytes = self._generate_qr_png(qr_url)
        svg_data = self._generate_qr_svg(qr_url)

        # Store PNG as base64 data URL
        png_b64 = base64.b64encode(png_bytes).decode("utf-8")
        qr_image_url = f"data:image/png;base64,{png_b64}"

        # Check if QR already exists
        result = await self.db.execute(select(QRCode).where(QRCode.shop_id == shop.id))
        existing_qr = result.scalar_one_or_none()

        if existing_qr:
            existing_qr.qr_url = qr_url
            existing_qr.qr_image_url = qr_image_url
            existing_qr.qr_svg_data = svg_data
            qr_code = existing_qr
        else:
            qr_code = QRCode(
                shop_id=shop.id,
                qr_url=qr_url,
                qr_image_url=qr_image_url,
                qr_svg_data=svg_data,
            )
            self.db.add(qr_code)

        # Log activity
        activity = ActivityLog(
            user_id=user_id,
            action="qr_generate",
            details=f"Generated QR code for {shop.name}",
        )
        self.db.add(activity)

        await self.db.flush()
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
