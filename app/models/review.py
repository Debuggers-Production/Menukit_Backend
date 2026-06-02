"""Menu item review model."""

import uuid
from sqlalchemy import String, Text, SmallInteger, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base, UUIDMixin, TimestampMixin


class MenuItemReview(Base, UUIDMixin, TimestampMixin):
    """A star rating + optional comment left by a customer on a menu item."""

    __tablename__ = "menu_item_reviews"

    menu_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reviewer_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)   # 1–5
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer_ip: Mapped[str | None] = mapped_column(String(50), nullable=True)  # for spam guard

    # Relationships
    menu_item = relationship("MenuItem", back_populates="reviews")
    shop = relationship("Shop", back_populates="reviews")
