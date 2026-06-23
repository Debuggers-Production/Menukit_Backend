"""Analytics API endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.core.deps import get_current_user
from app.schemas.analytics import AnalyticsResponse, OverviewStats, DailyReportResponse
from app.services.analytics_service import AnalyticsService
from app.models.user import User

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/dashboard", response_model=AnalyticsResponse)
async def get_dashboard_analytics(
    days: int = 30,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get full dashboard analytics payload."""
    service = AnalyticsService(db)
    
    overview = await service.get_overview(user.id)
    daily_scans = await service.get_daily_scans(user.id, days)
    top_items = await service.get_top_items(user.id, limit=5)
    top_searches = await service.get_top_searches(user.id, limit=10)
    top_reviews = await service.get_top_reviews(user.id, limit=5)
    
    # Get raw activities and convert to dict for schema validation
    raw_activities = await service.get_activity_log(user.id, limit=10)
    recent_activities = [
        {
            "id": str(act.id),
            "action": act.action,
            "details": act.details,
            "created_at": str(act.created_at)
        }
        for act in raw_activities
    ]
    
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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get analytics for a specific day."""
    service = AnalyticsService(db)
    return await service.get_daily_report(user.id, date)
