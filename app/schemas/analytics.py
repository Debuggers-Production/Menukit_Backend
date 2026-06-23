"""Analytics schemas."""

from typing import Optional, List
from pydantic import BaseModel


class OverviewStats(BaseModel):
    """Dashboard overview statistics."""
    total_menu_items: int = 0
    total_categories: int = 0
    total_qr_scans: int = 0
    total_menu_views: int = 0


class ScanData(BaseModel):
    """QR scan data point."""
    date: str
    count: int


class TopItem(BaseModel):
    """Most viewed/searched item."""
    name: str
    count: int


class SearchTermStat(BaseModel):
    """Search term statistics."""
    term: str
    count: int


class ActivityLogResponse(BaseModel):
    """Activity log entry."""
    id: str
    action: str
    details: Optional[str] = None
    created_at: str

    class Config:
        from_attributes = True


class DashboardReviewResponse(BaseModel):
    """Review entry for the dashboard."""
    id: str
    item_name: str
    reviewer_name: str
    rating: int
    comment: Optional[str] = None
    created_at: str


class AnalyticsResponse(BaseModel):
    """Full analytics response."""
    overview: OverviewStats
    daily_scans: List[ScanData] = []
    top_items: List[TopItem] = []
    top_searches: List[SearchTermStat] = []
    top_reviews: List[DashboardReviewResponse] = []
    recent_activities: List[ActivityLogResponse] = []


class DailyReportResponse(BaseModel):
    """Specific day analytics report."""
    date: str
    total_scans: int
    total_views: int
    total_searches: int
    repeated_customers_count: int
    top_items: List[TopItem] = []
    top_searches: List[SearchTermStat] = []
    repeated_customers: List[dict] = []
