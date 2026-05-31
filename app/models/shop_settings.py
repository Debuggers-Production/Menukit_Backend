"""Shop settings model."""

import uuid
from sqlalchemy import String, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base, UUIDMixin, TimestampMixin


class ShopSettings(Base, UUIDMixin, TimestampMixin):
    """Shop configuration settings model."""

    __tablename__ = "shop_settings"

    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    currency: Mapped[str] = mapped_column(String(10), default="₹", nullable=False)
    language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)
    show_prices: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    show_offers: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    shop = relationship("Shop", back_populates="settings")
