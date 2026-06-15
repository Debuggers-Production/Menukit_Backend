"""Customer Retailer Membership mapping model."""

import uuid
from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base, UUIDMixin, TimestampMixin


class CustomerRetailerMembership(Base, UUIDMixin, TimestampMixin):
    """Mapping table for global customers unlocking memberships at specific shops."""

    __tablename__ = "customer_retailer_memberships"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False, index=True
    )
    is_retailer_added: Mapped[bool] = mapped_column(
        default=False, server_default="false", nullable=False
    )

    __table_args__ = (
        UniqueConstraint("customer_id", "shop_id", name="uq_customer_shop_membership"),
    )

    # Relationships
    customer = relationship("Customer", back_populates="memberships")
    shop = relationship("Shop", back_populates="memberships")
