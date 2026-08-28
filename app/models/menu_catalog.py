"""Menu Catalog model."""

import uuid
from sqlalchemy import String, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base, UUIDMixin, TimestampMixin


class MenuCatalog(Base, UUIDMixin, TimestampMixin):
    """A central menu catalog that can be shared across multiple shop branches."""

    __tablename__ = "menu_catalogs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Relationships
    user = relationship("User", back_populates="menu_catalogs")
    shops = relationship("Shop", back_populates="menu_catalog", lazy="dynamic")
    categories = relationship("Category", back_populates="menu_catalog", lazy="selectin", cascade="all, delete-orphan", order_by="Category.display_order")
    menu_items = relationship("MenuItem", back_populates="menu_catalog", lazy="dynamic", cascade="all, delete-orphan")
    discounts = relationship("Discount", back_populates="menu_catalog", lazy="dynamic", cascade="all, delete-orphan")
