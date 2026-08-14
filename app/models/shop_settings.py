"""Shop settings model."""

import uuid
from sqlalchemy import String, Boolean, ForeignKey, Float
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base, UUIDMixin, TimestampMixin


class ShopSettings(Base, UUIDMixin, TimestampMixin):
    """Shop configuration settings model."""

    __tablename__ = "shop_settings"

    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    currency: Mapped[str] = mapped_column(String(10), default="₹", nullable=False)
    language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)
    show_prices: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    show_offers: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_discoverable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    show_menus_in_discovery: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Ordering & Payment settings
    delivery_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    base_delivery_charge: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    base_delivery_distance: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    extra_delivery_distance_step: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    extra_delivery_charge_per_step: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    takeaway_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    dinein_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auto_accept_orders: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cashfree_app_id: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    cashfree_secret_key: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    cashfree_sandbox: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    upi_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    beneficiary_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    encrypted_bank_account: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bank_account_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    ifsc_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    razorpay_account_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    razorpay_product_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    razorpay_route_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    online_payments_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    shop = relationship("Shop", back_populates="settings")
