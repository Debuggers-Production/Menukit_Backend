"""Order model."""

import uuid
from sqlalchemy import String, ForeignKey, Numeric, Boolean, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base, UUIDMixin, TimestampMixin


class Order(Base, UUIDMixin, TimestampMixin):
    """Order placed by a customer."""

    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_shop_created_at", "shop_id", "created_at"),
    )

    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_phone: Mapped[str] = mapped_column(String(50), nullable=False)
    order_type: Mapped[str] = mapped_column(String(50), nullable=False)  # 'delivery', 'dine_in', 'takeaway'
    table_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    delivery_address: Mapped[str | None] = mapped_column(String, nullable=True)
    order_status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False, index=True)  # 'pending', 'accepted', 'rejected', 'completed', 'cancelled'
    payment_status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False, index=True)  # 'pending', 'paid', 'failed'
    payment_method: Mapped[str] = mapped_column(String(50), default="cash", nullable=False)  # 'cash', 'online'
    total_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    cashfree_order_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payment_session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    credits_rewarded: Mapped[bool | None] = mapped_column(Boolean, default=False, nullable=True)
    razorpay_order_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Relationships
    shop = relationship("Shop", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan", lazy="selectin")


class OrderItem(Base, UUIDMixin, TimestampMixin):
    """Line items for an order."""

    __tablename__ = "order_items"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    menu_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_items.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False)
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    variant_info: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    addons_info: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # Relationships
    order = relationship("Order", back_populates="items")
