"""Main API router."""

from fastapi import APIRouter

from app.api.v1 import (
    auth, shops, categories, menu_items, employees,
    upload, qr, analytics, public, admin, discounts, bulk_upload,
    customers, memberships, notifications, subscription, seo, order, contests, settlements, whatsapp, razorpay_webhook, mcp_web_auth,
    oauth, well_known, broadcasts, printer
)

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

