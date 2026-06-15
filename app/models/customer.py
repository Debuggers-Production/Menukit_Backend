"""Customer model."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base, UUIDMixin, TimestampMixin


class Customer(Base, UUIDMixin, TimestampMixin):
    """Global customer model registered via mobile number."""

    __tablename__ = "customers"

    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mobile_number: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)

    # Relationships
    memberships = relationship("CustomerRetailerMembership", back_populates="customer", cascade="all, delete-orphan")
