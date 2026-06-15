"""Main API router."""

from fastapi import APIRouter

from app.api.v1 import (
    auth, shops, categories, menu_items,
    upload, qr, analytics, public, admin, discounts, bulk_upload,
    customers, memberships
)

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(shops.router)
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


