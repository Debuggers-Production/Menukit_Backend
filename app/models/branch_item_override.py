"""Branch Item Override model."""

import uuid
from sqlalchemy import ForeignKey, Float, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base, UUIDMixin, TimestampMixin


class BranchItemOverride(Base, UUIDMixin, TimestampMixin):
    """Overrides for a specific menu item for a specific shop branch."""

    __tablename__ = "branch_item_overrides"

    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False, index=True
    )
    menu_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_items.id", ondelete="CASCADE"), nullable=False, index=True
    )

    override_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_available: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # Relationships
    shop = relationship("Shop", back_populates="item_overrides")
    menu_item = relationship("MenuItem", back_populates="branch_overrides")
