"""Broadcast Campaign model for WhatsApp Marketing."""

import uuid
from datetime import datetime
from sqlalchemy import String, Text, Integer, ForeignKey, DateTime, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base, UUIDMixin, TimestampMixin


class BroadcastCampaign(Base, UUIDMixin, TimestampMixin):
    """WhatsApp broadcast marketing campaign model."""

    __tablename__ = "broadcast_campaigns"
    __table_args__ = (
        Index("ix_broadcast_shop_status", "shop_id", "status"),
        Index("ix_broadcast_scheduled", "status", "scheduled_at"),
    )

    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    target_audience: Mapped[str] = mapped_column(String(50), default="all", nullable=False)  # 'all', 'new', 'min_visits'
    min_visits: Mapped[int | None] = mapped_column(Integer, nullable=True, default=2)
    status: Mapped[str] = mapped_column(String(50), default="DRAFT", nullable=False)  # 'DRAFT', 'SCHEDULED', 'PROCESSING', 'SENT', 'FAILED'
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_recipients: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sent_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_details: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    shop = relationship("Shop", backref="broadcast_campaigns")
