"""User model."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base, UUIDMixin, TimestampMixin


class User(Base, UUIDMixin, TimestampMixin):
    """User account model."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="owner", nullable=False)  # owner | admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    shop = relationship("Shop", back_populates="user", uselist=False, lazy="selectin")
    sessions = relationship("Session", back_populates="user", lazy="dynamic")
    activity_logs = relationship("ActivityLog", back_populates="user", lazy="dynamic")
    otp_codes = relationship("OTPCode", back_populates="user", lazy="dynamic")
