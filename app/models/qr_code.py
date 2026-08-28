"""QR code model."""

import uuid
from sqlalchemy import String, Text, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base, UUIDMixin, TimestampMixin


class QRCode(Base, UUIDMixin, TimestampMixin):
    """QR code generated for a shop."""

    __tablename__ = "qr_codes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    qr_url: Mapped[str] = mapped_column(String(500), nullable=False)
    qr_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    qr_svg_data: Mapped[str | None] = mapped_column(Text, nullable=True)

    # QR Code Styling preferences
    dot_type: Mapped[str] = mapped_column(String(50), nullable=False, server_default="dots")
    corners_square_type: Mapped[str] = mapped_column(String(50), nullable=False, server_default="rounded")
    corners_dot_type: Mapped[str] = mapped_column(String(50), nullable=False, server_default="dot")
    qr_color: Mapped[str] = mapped_column(String(50), nullable=False, server_default="#1A1515")
    include_logo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    # Relationships
    user = relationship("User", back_populates="qr_code")
