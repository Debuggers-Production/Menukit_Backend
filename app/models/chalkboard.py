"""Chalkboard model."""

import uuid
from sqlalchemy import Text, String, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base, UUIDMixin, TimestampMixin


class Chalkboard(Base, UUIDMixin, TimestampMixin):
    """Restaurant A-frame sidewalk chalkboard configuration model."""

    __tablename__ = "chalkboards"

    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    shop = relationship("Shop", back_populates="chalkboard")
