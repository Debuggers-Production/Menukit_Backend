"""Theme settings model."""

import uuid
from sqlalchemy import String, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base, UUIDMixin, TimestampMixin


class ThemeSettings(Base, UUIDMixin, TimestampMixin):
    """Menu theme and appearance settings model."""

    __tablename__ = "theme_settings"

    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    theme: Mapped[str] = mapped_column(String(20), default="light", nullable=False)  # light | dark
    primary_color: Mapped[str] = mapped_column(String(20), default="#f97316", nullable=False)
    secondary_color: Mapped[str] = mapped_column(String(20), default="#1e293b", nullable=False)
    font_family: Mapped[str] = mapped_column(String(100), default="Inter", nullable=False)
    layout: Mapped[str] = mapped_column(String(20), default="grid", nullable=False)  # grid | list
    banner_style: Mapped[str] = mapped_column(String(20), default="hero", nullable=False)  # hero | carousel

    # Relationships
    shop = relationship("Shop", back_populates="theme")
