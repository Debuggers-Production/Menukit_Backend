from typing import List
import uuid
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.notification import NotificationResponse, MarkReadRequest
from app.schemas.common import MessageResponse
from app.services.notification_service import NotificationService
from app.services.websocket_manager import manager

router = APIRouter(prefix="/notifications", tags=["Notifications"])

@router.get("", response_model=List[NotificationResponse])
async def get_notifications(
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get recent notifications for the user's shop."""
    # Assuming user has a single shop for now.
    from app.services.shop_service import ShopService
    shop = await ShopService(db).get_shop_by_user(user.id)
    if not shop:
        return []

    service = NotificationService(db)
    return await service.get_recent_notifications(shop.id, limit)

@router.post("/mark-read", response_model=MessageResponse)
async def mark_notifications_read(
    data: MarkReadRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Mark specific or all notifications as read."""
    from app.services.shop_service import ShopService
    shop = await ShopService(db).get_shop_by_user(user.id)
    if not shop:
        return MessageResponse(message="No shop found")

    service = NotificationService(db)
    count = await service.mark_as_read(shop.id, data.notification_ids)
    
    return MessageResponse(message=f"Marked {count} notifications as read")

# We place the websocket endpoint here.
@router.websocket("/ws/{shop_id}")
async def websocket_endpoint(websocket: WebSocket, shop_id: str, db: AsyncSession = Depends(get_db)):
    """Connect a shop owner to their notification stream."""
    await manager.connect(shop_id, websocket)
    
    try:
        # Fetch unread notifications and send them immediately
        service = NotificationService(db)
        unread = await service.get_unread_notifications(uuid.UUID(shop_id))
        if unread:
            await manager.send_personal_message(
                message='{"type": "UNREAD_HISTORY", "data": ' + str([u.model_dump(mode='json') for u in unread]).replace("'", '"') + '}',
                websocket=websocket
            )
            
        while True:
            # We just wait for messages from the client.
            # Usually clients don't send anything, but they might send a ping.
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(shop_id, websocket)
