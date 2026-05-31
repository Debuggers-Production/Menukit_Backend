"""QR code model."""

import uuid
from sqlalchemy import String, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base, UUIDMixin, TimestampMixin


class QRCode(Base, UUIDMixin, TimestampMixin):
    """QR code generated for a shop."""

    __tablename__ = "qr_codes"

    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    qr_url: Mapped[str] = mapped_column(String(500), nullable=False)
    qr_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    qr_svg_data: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    shop = relationship("Shop", back_populates="qr_code")
