"""Device Token model for FCM Push Notifications."""

import uuid
from sqlalchemy import String, Boolean, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base, UUIDMixin, TimestampMixin


class DeviceToken(Base, UUIDMixin, TimestampMixin):
    """Device token model for FCM push notifications across web, iOS, and Android."""

    __tablename__ = "device_tokens"
    __table_args__ = (
        Index("ix_device_tokens_shop_active", "shop_id", "is_active"),
        Index("ix_device_tokens_phone_active", "customer_phone", "is_active"),
    )

    token: Mapped[str] = mapped_column(String(512), unique=True, index=True, nullable=False)
    
    # Association with shop (for merchant/staff notifications: orders, member registrations)
    shop_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=True, index=True
    )
    
    # Association with logged in user (owner/employee)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    
    # Association with customer (for customer order status updates)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    customer_phone: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)

    # Device & client metadata
    platform: Mapped[str] = mapped_column(String(50), default="web", nullable=False)  # 'web', 'android', 'ios'
    device_type: Mapped[str | None] = mapped_column(String(50), default="desktop", nullable=True)  # 'desktop', 'mobile', 'tablet'
    browser: Mapped[str | None] = mapped_column(String(50), nullable=True)  # 'chrome', 'safari', 'firefox', 'edge'
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Active status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    # Relationships
    shop = relationship("Shop", backref="device_tokens")
    user = relationship("User", backref="device_tokens")
    customer = relationship("Customer", backref="device_tokens")
