"""Shop model."""

import uuid
from sqlalchemy import String, Text, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base, UUIDMixin, TimestampMixin


class Shop(Base, UUIDMixin, TimestampMixin):
    """Restaurant shop profile model."""

    __tablename__ = "shops"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    welcome_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    banner_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    whatsapp: Mapped[str | None] = mapped_column(String(20), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    opening_time: Mapped[str | None] = mapped_column(String(20), nullable=True)
    closing_time: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    user = relationship("User", back_populates="shop")
    settings = relationship("ShopSettings", back_populates="shop", uselist=False, lazy="selectin", cascade="all, delete-orphan")
    theme = relationship("ThemeSettings", back_populates="shop", uselist=False, lazy="selectin", cascade="all, delete-orphan")
    categories = relationship("Category", back_populates="shop", lazy="selectin", cascade="all, delete-orphan", order_by="Category.display_order")
    menu_items = relationship("MenuItem", back_populates="shop", lazy="dynamic", cascade="all, delete-orphan")
    qr_code = relationship("QRCode", back_populates="shop", uselist=False, lazy="selectin", cascade="all, delete-orphan")
    qr_scans = relationship("QRScan", back_populates="shop", lazy="dynamic")
    menu_views = relationship("MenuView", back_populates="shop", lazy="dynamic")
    search_history = relationship("SearchHistory", back_populates="shop", lazy="dynamic")
