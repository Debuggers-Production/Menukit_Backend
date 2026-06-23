"""Subscription and Payment models."""

import uuid
from datetime import datetime
from sqlalchemy import String, Text, Boolean, ForeignKey, Float, DateTime, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base, UUIDMixin, TimestampMixin


class Subscription(Base, UUIDMixin, TimestampMixin):
    """Tracks the active subscription and features for a shop."""

    __tablename__ = "subscriptions"

    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    
    # Subscription status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_all_access: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    
    # JSON array of module string IDs (e.g., ["member-count", "search-data"])
    active_modules: Mapped[list | dict | None] = mapped_column(JSON, nullable=True, default=list)

    # Billing info
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    razorpay_subscription_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Relationships
    shop = relationship("Shop", back_populates="subscription")


class PaymentTransaction(Base, UUIDMixin, TimestampMixin):
    """Tracks individual payment attempts and successes."""

    __tablename__ = "payment_transactions"

    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False
    )
    
    razorpay_order_id: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    razorpay_payment_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    razorpay_signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    amount: Mapped[float] = mapped_column(Float, nullable=False) # In INR
    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)
    
    status: Mapped[str] = mapped_column(String(50), default="created", nullable=False) # created, success, failed
    
    # Metadata about what was purchased
    is_all_access: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    purchased_modules: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)

    # Relationships
    shop = relationship("Shop", back_populates="payment_transactions")
