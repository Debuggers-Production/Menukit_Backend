from sqlalchemy import Column, String, Boolean, ForeignKey, DateTime, func, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid

from app.database.base import Base

class Notification(Base):
    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shop_id = Column(UUID(as_uuid=True), ForeignKey("shops.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Type of notification: 'NEW_CUSTOMER', 'NEW_REVIEW', 'SYSTEM', etc.
    type = Column(String(50), nullable=False)
    
    # Title and body of the notification
    title = Column(String(100), nullable=False)
    message = Column(Text, nullable=False)
    
    # Payload for routing/data (e.g., {"customer_id": "...", "review_id": "..."})
    metadata_json = Column(Text, nullable=True)
    
    is_read = Column(Boolean, default=False, nullable=False, index=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    # Relationship to shop
    shop = relationship("Shop", backref="notifications")
