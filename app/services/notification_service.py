import uuid
import json
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.models.notification import Notification
from app.schemas.notification import NotificationResponse
from app.services.websocket_manager import manager

class NotificationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_notification(self, shop_id: uuid.UUID, type: str, title: str, message: str, metadata: dict = None) -> Notification:
        metadata_json = json.dumps(metadata) if metadata else None
        
        notification = Notification(
            shop_id=shop_id,
            type=type,
            title=title,
            message=message,
            metadata_json=metadata_json,
            is_read=False
        )
        self.db.add(notification)
        await self.db.commit()
        await self.db.refresh(notification)

        # Broadcast via WebSocket if the shop is connected
        notif_response = self._to_response(notification)
        await manager.broadcast_to_shop(str(shop_id), {
            "type": "NEW_NOTIFICATION",
            "data": notif_response.model_dump(mode='json')
        })

        return notification

    async def get_unread_notifications(self, shop_id: uuid.UUID) -> List[NotificationResponse]:
        result = await self.db.execute(
            select(Notification)
            .where(Notification.shop_id == shop_id, Notification.is_read == False)
            .order_by(Notification.created_at.desc())
        )
        notifications = result.scalars().all()
        return [self._to_response(n) for n in notifications]

    async def get_recent_notifications(self, shop_id: uuid.UUID, limit: int = 50) -> List[NotificationResponse]:
        result = await self.db.execute(
            select(Notification)
            .where(Notification.shop_id == shop_id)
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
        notifications = result.scalars().all()
        return [self._to_response(n) for n in notifications]

    async def mark_as_read(self, shop_id: uuid.UUID, notification_ids: Optional[List[uuid.UUID]] = None) -> int:
        query = update(Notification).where(Notification.shop_id == shop_id).values(is_read=True)
        if notification_ids:
            query = query.where(Notification.id.in_(notification_ids))
            
        result = await self.db.execute(query)
        await self.db.commit()
        return result.rowcount

    def _to_response(self, n: Notification) -> NotificationResponse:
        return NotificationResponse(
            id=n.id,
            shop_id=n.shop_id,
            type=n.type,
            title=n.title,
            message=n.message,
            metadata_json=n.metadata_json,
            is_read=n.is_read,
            created_at=n.created_at
        )
