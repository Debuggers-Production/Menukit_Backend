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


class TopOrderedFoodItem(BaseModel):
    """Top ordered food item with revenue."""
    name: str
    total_quantity: int
    total_revenue: float


class DailySalesReportPoint(BaseModel):
    """Daily revenue and orders report point."""
    date: str
    orders_count: int
    gross_revenue: float
    commission_amount: float
    settled_amount: float


class OrderSettlementInvoice(BaseModel):
    """Invoice & settlement detail for an order."""
    order_id: str
    invoice_no: str
    payment_id: Optional[str] = None
    payment_method: str
    customer_name: str
    customer_phone: Optional[str] = None
    total_order_amt: float
    commission_rate: float
    commission_amount: float
    settled_amount: float
    order_status: str
    created_at: str


class TopOrderedCategory(BaseModel):
    """Top ordered category with revenue."""
    name: str
    total_quantity: int
    total_revenue: float

class RevenueAnalyticsSummary(BaseModel):
    """Revenue & Sales summary analytics."""
    total_gross_revenue: float
    total_settled_amount: float
    total_commission_paid: float
    total_orders_count: int
    highest_revenue_food: Optional[TopOrderedFoodItem] = None
    most_ordered_food: Optional[TopOrderedFoodItem] = None
    growth_ratio: float
    top_ordered_items: List[TopOrderedFoodItem] = []
    top_ordered_categories: List[TopOrderedCategory] = []
    daily_sales: List[DailySalesReportPoint] = []
    recent_invoices: List[OrderSettlementInvoice] = []


class GstInvoiceEntry(BaseModel):
    """Single invoice tax entry for GSTR reporting."""
    order_id: str
    invoice_no: str
    date: str
    customer_name: str
    customer_phone: Optional[str] = None
    order_type: str
    payment_method: str
    payment_status: str
    gross_amount: float
    taxable_amount: float
    cgst_amount: float
    sgst_amount: float
    total_tax_amount: float
    cgst_rate: float
    sgst_rate: float


class GstComplianceInfo(BaseModel):
    """Compliance and tax registration snapshot."""
    gst_enabled: bool = False
    gstin: Optional[str] = None
    legal_name: Optional[str] = None
    fssai_license: Optional[str] = None
    cgst_rate: float = 2.5
    sgst_rate: float = 2.5
    inclusive_tax: bool = False


class GstReportSummary(BaseModel):
    """GST and tax compliance summary for analytics."""
    total_gross_turnover: float
    total_taxable_turnover: float
    total_cgst_collected: float
    total_sgst_collected: float
    total_gst_collected: float
    total_invoices_count: int
    compliance: GstComplianceInfo
    invoices: List[GstInvoiceEntry] = []

