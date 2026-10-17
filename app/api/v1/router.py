"""Main API router."""

from fastapi import APIRouter,Query

from app.api.v1 import (
    auth, shops, categories, menu_items, employees,
    upload, qr, analytics, public, admin, discounts, bulk_upload,
    customers, memberships, notifications, subscription, seo, order, contests, settlements, whatsapp, razorpay_webhook, mcp_web_auth,
    oauth, well_known, broadcasts, printer, schemes, scheduled_notifications, test_emails
)
from typing import Optional, List
from app.core.config import get_settings

settings = get_settings()
api_router = APIRouter()

api_router.include_router(well_known.router)
api_router.include_router(oauth.router)
api_router.include_router(auth.router)
api_router.include_router(mcp_web_auth.router)
api_router.include_router(shops.router)
api_router.include_router(employees.router)
api_router.include_router(categories.router)
api_router.include_router(menu_items.router)
api_router.include_router(upload.router)
api_router.include_router(qr.router)
api_router.include_router(analytics.router)
api_router.include_router(public.router)
api_router.include_router(public.shops_router)
api_router.include_router(admin.router)
api_router.include_router(discounts.router)
api_router.include_router(bulk_upload.router)
api_router.include_router(customers.router)
api_router.include_router(memberships.router)
api_router.include_router(notifications.router)
api_router.include_router(subscription.router, prefix="/subscription", tags=["Subscription"])
api_router.include_router(seo.seo_router, prefix="/seo", tags=["SEO"])
api_router.include_router(order.router)
api_router.include_router(contests.router)
api_router.include_router(settlements.router)
api_router.include_router(whatsapp.router)
api_router.include_router(razorpay_webhook.router)
api_router.include_router(broadcasts.router)
api_router.include_router(printer.router)
api_router.include_router(schemes.router)
api_router.include_router(schemes.public_router)
api_router.include_router(scheduled_notifications.router)

# Testing routes are strictly excluded from production environments
if not getattr(settings, "is_production", False):
    api_router.include_router(test_emails.router)

