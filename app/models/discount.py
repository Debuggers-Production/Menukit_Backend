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

    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
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
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    members_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    shop = relationship("Shop", back_populates="discounts")
