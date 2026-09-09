"""Discount model for shop-wide promotions."""

import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Text, Boolean, Numeric, ForeignKey, DateTime, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base, UUIDMixin, TimestampMixin


class Discount(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "discounts"

    menu_catalog_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_catalogs.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # "percentage", "flat", "bogo", "combo"
    discount_type: Mapped[str] = mapped_column(String(20), default="percentage", nullable=False)
    discount_value: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)

    # Advanced mechanics (BOGO & Combo)
    buy_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    get_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reward_target_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # "all" | "category" | "items"
    applies_to: Mapped[str] = mapped_column(String(20), default="all", nullable=False)
    # List of category IDs or item IDs when applies_to != "all"
    target_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Scheduling & Availability
    available_days: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    available_time_presets: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    visibility_type: Mapped[str] = mapped_column(String(50), default="everyone_unlock_members", server_default="everyone_unlock_members", nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    # Relationships
    menu_catalog = relationship("MenuCatalog", back_populates="discounts")
    redemptions = relationship("DiscountRedemption", back_populates="discount", cascade="all, delete-orphan")


class DiscountRedemption(Base, UUIDMixin, TimestampMixin):
    """Tracks unique customer discount redemptions to prevent reuse."""
    __tablename__ = "discount_redemptions"

    discount_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("discounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    redeemed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    customer_identifier: Mapped[str | None] = mapped_column(String(100), nullable=True)
    redeemed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    discount = relationship("Discount", back_populates="redemptions")
    shop = relationship("Shop")


class CustomerDiscountCode(Base, UUIDMixin, TimestampMixin):
    """Tracks unique discount codes assigned to individual customers."""
    __tablename__ = "customer_discount_codes"

    discount_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("discounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    customer_identifier: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    is_redeemed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    discount = relationship("Discount")
    shop = relationship("Shop")
    customer = relationship("Customer")
