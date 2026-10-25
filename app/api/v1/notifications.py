from typing import List, Optional
import uuid
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.core.deps import get_current_user, get_optional_current_user
from app.models.user import User
from app.schemas.notification import (
    NotificationResponse,
    MarkReadRequest,
    FCMRegisterTokenRequest,
    FCMUnregisterTokenRequest,
    FCMTestNotificationRequest,
)
from app.schemas.common import MessageResponse
from app.services.notification_service import NotificationService
from app.services.fcm_service import FCMService
from app.services.websocket_manager import manager

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("/fcm/status")
async def get_fcm_status():
    """Check if Firebase Cloud Messaging is configured and ready."""
    is_ready = FCMService.is_configured()
    return {
        "fcm_configured": is_ready,
        "status": "ready" if is_ready else "not_configured",
        "message": "FCM is ready for push notifications" if is_ready else "Firebase credentials not found in backend configuration",
    }


@router.get("/fcm/tokens")
async def list_fcm_tokens(
    db: AsyncSession = Depends(get_db),
):
    """List all registered device tokens with their shop and active status."""
    from sqlalchemy import select
    from app.models.device_token import DeviceToken
    result = await db.execute(select(DeviceToken).order_by(DeviceToken.created_at.desc()))
    devices = result.scalars().all()
    return [
        {
            "id": str(d.id),
            "token": d.token,
            "shop_id": str(d.shop_id) if d.shop_id else None,
            "customer_phone": d.customer_phone,
            "platform": d.platform,
            "device_type": d.device_type,
            "is_active": d.is_active,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in devices
    ]


@router.post("/fcm/register", response_model=MessageResponse)
async def register_fcm_device(
    data: FCMRegisterTokenRequest,
    user_agent: Optional[str] = Header(None),
    optional_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Register or refresh an FCM device registration token for Web, iOS, or Android."""
    fcm_service = FCMService(db)
    user_id = optional_user.id if optional_user else None
    
    # If shop_id not in request body, try to resolve from user's shop
    shop_id = data.shop_id
    if not shop_id and optional_user:
        from app.services.shop_service import ShopService
        shop = await ShopService(db).get_shop_by_user(optional_user.id)
        if shop:
            shop_id = shop.id

    print(f"\033[96m[API /fcm/register]\033[0m Incoming token registration | Shop: {shop_id} | Platform: {data.platform} | Token: {data.token[:30]}...")

    await fcm_service.register_device(
        token=data.token,
        shop_id=shop_id,
        user_id=user_id,
        customer_id=data.customer_id,
        customer_phone=data.customer_phone,
        platform=data.platform or "web",
        device_type=data.device_type or "desktop",
        browser=data.browser,
        user_agent=data.user_agent or user_agent,
    )
    return MessageResponse(message="FCM device token registered successfully")



@router.post("/fcm/unregister", response_model=MessageResponse)
async def unregister_fcm_device(
    data: FCMUnregisterTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    """Unregister/deactivate an FCM device token upon user logout."""
    fcm_service = FCMService(db)
    success = await fcm_service.unregister_device(data.token)
    return MessageResponse(message="FCM token unregistered" if success else "Token not found or already inactive")


@router.post("/fcm/test")
async def test_fcm_notification(
    data: FCMTestNotificationRequest,
    optional_user: Optional[User] = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Send a test push notification to verify push delivery on Laptop, iOS, or Android."""
    fcm_service = FCMService(db)
    
    # Resolve shop_id if user logged in
    shop_id = data.shop_id
    if not shop_id and optional_user:
        from app.services.shop_service import ShopService
        shop = await ShopService(db).get_shop_by_user(optional_user.id)
        if shop:
            shop_id = shop.id

    if data.token:
        result = await fcm_service.send_to_token(
            token=data.token,
            title=data.title,
            body=data.body,
            data={"test": "true", "timestamp": str(uuid.uuid4())},
            url=data.url or "/orders",
            notification_type="TEST",
        )
    elif shop_id:
        result = await fcm_service.send_to_shop(
            shop_id=shop_id,
            title=data.title,
            body=data.body,
            data={"test": "true", "shop_id": str(shop_id)},
            url=data.url or "/orders",
            notification_type="TEST",
        )
    elif data.customer_phone:
        result = await fcm_service.send_to_customer(
            customer_phone=data.customer_phone,
            title=data.title,
            body=data.body,
            data={"test": "true", "phone": data.customer_phone},
            url=data.url or "/orders",
            notification_type="TEST",
        )
    else:
        return {
            "success": False,
            "message": "Please provide a token, shop_id, or customer_phone to test push notification.",
        }

    return {
        "success": result.get("success_count", 0) > 0,
        "result": result,
        "message": f"Push sent. Success: {result.get('success_count', 0)}, Failed: {result.get('failure_count', 0)}",
    }


@router.get("", response_model=List[NotificationResponse])
async def get_notifications(
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get recent notifications for the user's shop."""
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


@router.websocket("/ws/{shop_id}")
async def websocket_endpoint(websocket: WebSocket, shop_id: str, db: AsyncSession = Depends(get_db)):
    """Connect a shop owner to their notification stream."""
    await manager.connect(shop_id, websocket)
    
    try:
        service = NotificationService(db)
        unread = await service.get_unread_notifications(uuid.UUID(shop_id))
        if unread:
            import json
            payload = {
                "type": "UNREAD_HISTORY",
                "data": [u.model_dump(mode='json') for u in unread]
            }
            await manager.send_personal_message(
                message=json.dumps(payload, default=str),
                websocket=websocket
            )
            
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(shop_id, websocket)

