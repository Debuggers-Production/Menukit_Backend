"""Scheme (Pandu) models for Bakeries and Cracker shops."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import String, Text, Boolean, ForeignKey, DateTime, Integer, Numeric, Date
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base, UUIDMixin, TimestampMixin


class Scheme(Base, UUIDMixin, TimestampMixin):
    """Savings Scheme (formerly called Pandu) created by Bakery or Cracker shops."""
    __tablename__ = "schemes"

    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Installment price (e.g. ₹500 per month or ₹100 per week)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    # Frequency: "monthly" | "weekly"
    frequency: Mapped[str] = mapped_column(String(20), default="monthly", nullable=False)

    # Term duration number (e.g. 12, 10, 52)
    term_duration: Mapped[int] = mapped_column(Integer, default=12, nullable=False)
    # Unit: "months" | "weeks" | "years"
    term_unit: Mapped[str] = mapped_column(String(20), default="months", nullable=False)

    # Members limit: None for unlimited, or integer limit (e.g. 50, 100)
    max_members: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Items / Products included in the scheme (including variant info)
    # List of: { "item_id": str, "name": str, "variant_name": str | None, "quantity": int, "price": float, "image_url": str | None }
    items: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    # Public visibility toggle
    show_on_public_menu: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Status: "active" | "closed" | "completed"
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)

    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    shop = relationship("Shop", back_populates="schemes")
    members = relationship("SchemeMember", back_populates="scheme", cascade="all, delete-orphan", order_by="SchemeMember.created_at.desc()")
    payments = relationship("SchemePayment", back_populates="scheme", cascade="all, delete-orphan")


class SchemeMember(Base, UUIDMixin, TimestampMixin):
    """Enrolled customer / member in a Scheme."""
    __tablename__ = "scheme_members"

    scheme_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("schemes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    customer_address: Mapped[str | None] = mapped_column(Text, nullable=True)

    member_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)  # active | completed | cancelled
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    total_installments: Mapped[int] = mapped_column(Integer, default=12, nullable=False)
    paid_installments: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    scheme = relationship("Scheme", back_populates="members")
    payments = relationship("SchemePayment", back_populates="member", cascade="all, delete-orphan", order_by="SchemePayment.installment_number.asc()")


class SchemePayment(Base, UUIDMixin, TimestampMixin):
    """Individual installment payment recorded for a scheme member."""
    __tablename__ = "scheme_payments"

    scheme_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("schemes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scheme_members.id", ondelete="CASCADE"), nullable=False, index=True
    )
    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False, index=True
    )

    installment_number: Mapped[int] = mapped_column(Integer, nullable=False)  # 1, 2, 3...
    installment_label: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g. "Month 1 (Oct 2026)", "Week 1"
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    # Payment status: "paid" | "pending" | "due"
    status: Mapped[str] = mapped_column(String(20), default="paid", nullable=False)
    payment_method: Mapped[str] = mapped_column(String(50), default="cash", nullable=False)  # cash | upi | card | online
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    transaction_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Settlement tracking
    settlement_status: Mapped[str | None] = mapped_column(String(50), nullable=True)  # "settled" | "pending"
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    razorpay_settlement_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Relationships
    scheme = relationship("Scheme", back_populates="payments")
    member = relationship("SchemeMember", back_populates="payments")
