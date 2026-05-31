"""Menu image model."""

import uuid
from sqlalchemy import String, Integer, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base, UUIDMixin, TimestampMixin


class MenuImage(Base, UUIDMixin, TimestampMixin):
    """Image attached to a menu item."""

    __tablename__ = "menu_images"

    menu_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_items.id", ondelete="CASCADE"), nullable=False
    )
    image_url: Mapped[str] = mapped_column(String(500), nullable=False)
    thumbnail_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    menu_item = relationship("MenuItem", back_populates="images")
