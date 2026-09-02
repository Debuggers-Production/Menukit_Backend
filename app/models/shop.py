"""Shop model."""

import uuid
from sqlalchemy import String, Text, Boolean, ForeignKey, Float, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base, UUIDMixin, TimestampMixin


class Shop(Base, UUIDMixin, TimestampMixin):
    """Restaurant shop profile model."""

    __tablename__ = "shops"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    menu_catalog_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_catalogs.id", ondelete="SET NULL"), nullable=True, index=True
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
    category: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    cuisine: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    area: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    opening_time: Mapped[str | None] = mapped_column(String(20), nullable=True)
    closing_time: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    google_review_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_widget_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    broadcast_credits: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


    # Relationships
    user = relationship("User", back_populates="shops")
    menu_catalog = relationship("MenuCatalog", back_populates="shops")
    item_overrides = relationship("BranchItemOverride", back_populates="shop", lazy="dynamic", cascade="all, delete-orphan")
    settings = relationship("ShopSettings", back_populates="shop", uselist=False, lazy="selectin", cascade="all, delete-orphan")
    theme = relationship("ThemeSettings", back_populates="shop", uselist=False, lazy="selectin", cascade="all, delete-orphan")
    qr_scans = relationship("QRScan", back_populates="shop", lazy="dynamic")
    menu_views = relationship("MenuView", back_populates="shop", lazy="dynamic")
    search_history = relationship("SearchHistory", back_populates="shop", lazy="dynamic")
    reviews = relationship("MenuItemReview", back_populates="shop", lazy="dynamic", cascade="all, delete-orphan")
    memberships = relationship("CustomerRetailerMembership", back_populates="shop", lazy="dynamic", cascade="all, delete-orphan")
    subscription = relationship("Subscription", back_populates="shop", uselist=False, lazy="selectin", cascade="all, delete-orphan")
    payment_transactions = relationship("PaymentTransaction", back_populates="shop", lazy="dynamic", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="shop", lazy="dynamic", cascade="all, delete-orphan")
    contests = relationship("Contest", back_populates="shop", lazy="dynamic", cascade="all, delete-orphan")
    employees = relationship("Employee", back_populates="shop", lazy="dynamic", cascade="all, delete-orphan")
