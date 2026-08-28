"""Analytics API endpoints."""

import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.core.deps import get_current_user, require_permission
from app.schemas.analytics import AnalyticsResponse, OverviewStats, DailyReportResponse, RevenueAnalyticsSummary
from app.services.analytics_service import AnalyticsService
from app.models.user import User

router = APIRouter(prefix="/analytics", tags=["Analytics"])


async def check_analytics_subscription(shop, db: AsyncSession):
    """Backend subscription verification for analytics endpoints."""
    from app.services.subscription_helper import get_shop_subscription_permissions
    from fastapi import HTTPException
    perms = await get_shop_subscription_permissions(shop.id, db)
    if perms["is_expired"] or not (perms["analytics_advanced"] or perms["analytics_customer"]):
        raise HTTPException(
            status_code=403,
            detail="Subscription required: Analytics features are locked due to an inactive or missing analytics module. Please purchase an Analytics module."
        )


@router.get("/revenue", response_model=RevenueAnalyticsSummary)
async def get_revenue_analytics(
    days: int = 30,
    start_date: str | None = None,
    end_date: str | None = None,
    shop = Depends(require_permission("analytics", "read")),
    db: AsyncSession = Depends(get_db),
):
    """Get order revenue, top ordered items, daily breakdown, settlement invoices and growth ratio."""
    await check_analytics_subscription(shop, db)
    service = AnalyticsService(db)
    return await service.get_revenue_analytics(shop.id, days=days, start_date=start_date, end_date=end_date)


@router.get("/dashboard", response_model=AnalyticsResponse)
async def get_dashboard_analytics(
    days: int = 30,
    shop = Depends(require_permission("analytics", "read")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get full dashboard overview analytics payload (Free core metric dashboard)."""
    service = AnalyticsService(db)
    
    from app.services.subscription_helper import get_shop_subscription_permissions
    
    overview = await service.get_overview(shop.id)
    daily_scans = await service.get_daily_scans(shop.id, days)
    top_searches = []
    has_orders_perm = False
    
    perms = await get_shop_subscription_permissions(shop.id, db)
    has_orders_perm = perms.get("online_orders", False)
    if perms.get("search_data"):
        top_searches = await service.get_top_searches(shop.id, limit=10)
            
    top_items = await service.get_top_items(shop.id, limit=5) if has_orders_perm else []
    top_reviews = await service.get_top_reviews(shop.id, limit=5)
    
    # Get raw activities and filter out order activities if online_orders permission is False
    raw_activities = await service.get_activity_log(user.id, limit=25)
    recent_activities = []
    for act in raw_activities:
        if not has_orders_perm and act.action and (act.action.startswith("order_") or "Order " in (act.details or "")):
            continue
        recent_activities.append({
            "id": str(act.id),
            "action": act.action,
            "details": act.details,
            "created_at": str(act.created_at)
        })
        if len(recent_activities) >= 10:
            break
    
    return AnalyticsResponse(
        overview=OverviewStats(**overview),
        daily_scans=daily_scans,
        top_items=top_items,
        top_searches=top_searches,
        top_reviews=top_reviews,
        recent_activities=recent_activities
    )

@router.get("/daily", response_model=DailyReportResponse)
async def get_daily_analytics(
    date: str,
    shop = Depends(require_permission("analytics", "read")),
    db: AsyncSession = Depends(get_db),
):
    """Get analytics for a specific day."""
    await check_analytics_subscription(shop, db)
    service = AnalyticsService(db)
    return await service.get_daily_report(shop.id, date)


@router.get("/top-searches")
async def get_top_customer_searches(
    limit: int = 10,
    shop = Depends(require_permission("analytics", "read")),
    db: AsyncSession = Depends(get_db),
):
    """
    Dedicated endpoint for Customer Search Analytics.
    Protected strictly under search_data subscription permission.
    Returns 403 Forbidden if search_data module is inactive or missing.
    """
    from app.services.subscription_helper import get_shop_subscription_permissions
    from fastapi import HTTPException

    perms = await get_shop_subscription_permissions(shop.id, db)
    if perms["is_expired"] or not perms["search_data"]:
        raise HTTPException(
            status_code=403,
            detail="Subscription required: Customer Search Analytics is locked due to an inactive or missing search-data module."
        )

    service = AnalyticsService(db)
    searches = await service.get_top_searches(shop.id, limit=limit)
    return {"top_searches": searches}
