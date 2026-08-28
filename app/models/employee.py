"""Employee model."""

import uuid
from sqlalchemy import String, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base, UUIDMixin, TimestampMixin


class Employee(Base, UUIDMixin, TimestampMixin):
    """Employee model linking users to shops with permissions."""

    __tablename__ = "employees"

    shop_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)  # pending, active
    permissions: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    verification_token: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, nullable=True)

    # Relationships
    shop = relationship("Shop", back_populates="employees", lazy="selectin")
    user = relationship("User", back_populates="employments", lazy="selectin")
