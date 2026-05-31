"""Menu item model."""

import uuid
from decimal import Decimal
from sqlalchemy import String, Text, Integer, Boolean, Numeric, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base, UUIDMixin, TimestampMixin


class MenuItem(Base, UUIDMixin, TimestampMixin):
    """Individual menu dish/item model."""

    __tablename__ = "menu_items"

    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    offer_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    food_type: Mapped[str] = mapped_column(String(10), default="veg", nullable=False)  # veg | non-veg
    is_bestseller: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_highlighted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    shop = relationship("Shop", back_populates="menu_items")
    category = relationship("Category", back_populates="menu_items")
    images = relationship(
        "MenuImage", back_populates="menu_item", lazy="selectin",
        cascade="all, delete-orphan", order_by="MenuImage.display_order"
    )
