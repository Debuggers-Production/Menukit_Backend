"""Contest models."""

import uuid
from datetime import datetime
from sqlalchemy import String, Text, Boolean, ForeignKey, DateTime, Integer, Float
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base, UUIDMixin, TimestampMixin


class Contest(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "contests"

    shop_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # "instant_cashback", "free_food", "discount", "offer"
    reward_type: Mapped[str] = mapped_column(String(50), default="discount", nullable=False)
    reward_value: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # "drawing", "kavithai"
    contest_type: Mapped[str] = mapped_column(String(50), default="drawing", nullable=False)

    # "all", "items"
    applies_to: Mapped[str] = mapped_column(String(20), default="all", nullable=False)
    # List of item IDs when applies_to == "items"
    target_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # "active", "completed", "cancelled"
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Minimum Targets & Criteria
    ranking_criterion: Mapped[str] = mapped_column(String(20), default="likes", nullable=False)  # "likes", "comments", "shares", "all"
    min_participants: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    min_likes: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    min_comments: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    min_shares: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cancel_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Relationships
    shop = relationship("Shop", back_populates="contests")
    participations = relationship("ContestParticipation", back_populates="contest", cascade="all, delete-orphan")


class ContestParticipation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "contest_participations"

    contest_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contests.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )

    # "drawing", "kavithai"
    content_type: Mapped[str] = mapped_column(String(50), nullable=False)
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    likes_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    comments_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    shares_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Timer fields (10 mins default = 600 seconds)
    time_remaining_seconds: Mapped[int] = mapped_column(Integer, default=600, nullable=False)
    is_timer_running: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    timer_last_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    is_submitted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    contest = relationship("Contest", back_populates="participations")
    customer = relationship("Customer")
    likes = relationship("ContestLike", back_populates="participation", cascade="all, delete-orphan")


class ContestCredit(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "contest_credits"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    credits: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Relationships
    customer = relationship("Customer")


class ContestLike(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "contest_likes"

    participation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contest_participations.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )

    # Relationships
    participation = relationship("ContestParticipation", back_populates="likes")
    customer = relationship("Customer")


class ContestComment(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "contest_comments"

    participation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contest_participations.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    likes_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    customer = relationship("Customer")
    likes = relationship("ContestCommentLike", back_populates="comment", cascade="all, delete-orphan")


class ContestCommentLike(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "contest_comment_likes"

    comment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contest_comments.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )

    # Relationships
    comment = relationship("ContestComment", back_populates="likes")
    customer = relationship("Customer")
