"""Scheduled notifications API endpoints for admin inspection and manual triggering."""

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import uuid

from app.database.session import get_db
from app.core.deps import get_current_admin
from app.models.user import User
from app.models.order import Order
from app.models.shop import Shop
from app.services.scheduled_notification_service import ScheduledNotificationService
from app.services.order_service import OrderService

router = APIRouter(prefix="/scheduled-notifications", tags=["Scheduled Notifications"])


@router.post("/run-subscription-checks")
async def trigger_subscription_checks(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """Trigger subscription expiration email checks (3 days before, and every 2 days after expired)."""
    result = await ScheduledNotificationService.process_subscription_expiry_checks(db)
    return result


@router.post("/run-weekend-reports")
async def trigger_weekend_reports(
    force: bool = Query(default=False, description="Force run even if today is not Saturday/Sunday"),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """Trigger weekend total customers count report emails to shop admins."""
    result = await ScheduledNotificationService.process_weekend_customer_reports(db, force=force)
    return result


from app.core.config import get_settings

if not get_settings().is_production:
    @router.post("/test-order-email/{order_id}")
    async def trigger_test_order_email(
        order_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        admin: User = Depends(get_current_admin)
    ):
        """Send a test new order notification email for an existing order."""
        order_service = OrderService(db)
        order = await order_service.get_order_by_id(order_id)
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        
        await order_service._send_order_admin_email_notification(order=order)
        return {"status": "success", "message": f"Order email dispatched for order {order_id}"}


@router.post("/run-scheme-reminders")
async def trigger_scheme_reminders(
    force: bool = Query(default=False, description="Force run even if today is not the 1-day-before reminder date"),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """Trigger WhatsApp payment reminders 1 day before due date for active scheme members."""
    result = await ScheduledNotificationService.process_scheme_payment_reminders(db, force=force)
    return result
