"""Analytics service for tracking and reporting."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, List

from sqlalchemy import select, func, desc, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.shop import Shop
from app.models.category import Category
from app.models.menu_item import MenuItem
from app.models.analytics import QRScan, MenuView, SearchHistory
from app.models.activity_log import ActivityLog
from app.core.exceptions import NotFoundException


class AnalyticsService:
    """Handles analytics tracking and dashboard data."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_shop_id(self, user_id: uuid.UUID) -> uuid.UUID:
        """Get shop ID for the authenticated user."""
        result = await self.db.execute(select(Shop.id).where(Shop.user_id == user_id))
        shop_id = result.scalar_one_or_none()
        if not shop_id:
            raise NotFoundException("Shop not found")
        return shop_id

    # ── Tracking ──────────────────────────────────────────────

    async def record_qr_scan(self, shop_id: uuid.UUID, ip: str = None, ua: str = None, ref: str = None):
        """Record a QR code scan."""
        scan = QRScan(shop_id=shop_id, ip_address=ip, user_agent=ua, referrer=ref)
        self.db.add(scan)
        await self.db.flush()

    async def record_menu_view(
        self, shop_id: uuid.UUID, item_id: uuid.UUID = None, category_id: uuid.UUID = None, ip: str = None
    ):
        """Record a menu page/item view."""
        view = MenuView(shop_id=shop_id, menu_item_id=item_id, category_id=category_id, ip_address=ip)
        self.db.add(view)
        await self.db.flush()

    async def record_search(self, shop_id: uuid.UUID, term: str, result_count: int = 0):
        """Record a customer search query."""
        entry = SearchHistory(shop_id=shop_id, search_term=term.lower().strip(), result_count=result_count)
        self.db.add(entry)
        await self.db.flush()

    # ── Dashboard Stats ───────────────────────────────────────

    async def get_overview(self, user_id: uuid.UUID) -> dict:
        """Get dashboard overview statistics."""
        shop_id = await self._get_shop_id(user_id)

        # Total menu items
        items_count = await self.db.execute(
            select(func.count(MenuItem.id)).where(MenuItem.shop_id == shop_id)
        )
        total_items = items_count.scalar() or 0

        # Total categories
        cats_count = await self.db.execute(
            select(func.count(Category.id)).where(Category.shop_id == shop_id)
        )
        total_categories = cats_count.scalar() or 0

        # Total QR scans
        scans_count = await self.db.execute(
            select(func.count(QRScan.id)).where(QRScan.shop_id == shop_id)
        )
        total_scans = scans_count.scalar() or 0

        # Total menu views
        views_count = await self.db.execute(
            select(func.count(MenuView.id)).where(MenuView.shop_id == shop_id)
        )
        total_views = views_count.scalar() or 0

        return {
            "total_menu_items": total_items,
            "total_categories": total_categories,
            "total_qr_scans": total_scans,
            "total_menu_views": total_views,
        }

    async def get_daily_scans(self, user_id: uuid.UUID, days: int = 30) -> List[dict]:
        """Get daily QR scan counts for the last N days."""
        shop_id = await self._get_shop_id(user_id)
        since = datetime.now(timezone.utc) - timedelta(days=days)

        result = await self.db.execute(
            select(
                func.date(QRScan.scanned_at).label("date"),
                func.count(QRScan.id).label("count"),
            )
            .where(QRScan.shop_id == shop_id, QRScan.scanned_at >= since)
            .group_by(func.date(QRScan.scanned_at))
            .order_by(func.date(QRScan.scanned_at))
        )

        return [{"date": str(row.date), "count": row.count} for row in result]

    async def get_top_items(self, user_id: uuid.UUID, limit: int = 10) -> List[dict]:
        """Get most viewed menu items."""
        shop_id = await self._get_shop_id(user_id)

        result = await self.db.execute(
            select(MenuItem.name, func.count(MenuView.id).label("count"))
            .join(MenuView, MenuView.menu_item_id == MenuItem.id)
            .where(MenuView.shop_id == shop_id, MenuView.menu_item_id.isnot(None))
            .group_by(MenuItem.name)
            .order_by(desc("count"))
            .limit(limit)
        )

        return [{"name": row.name, "count": row.count} for row in result]

    async def get_top_searches(self, user_id: uuid.UUID, limit: int = 10) -> List[dict]:
        """Get most searched terms."""
        shop_id = await self._get_shop_id(user_id)

        result = await self.db.execute(
            select(SearchHistory.search_term, func.count(SearchHistory.id).label("count"))
            .where(SearchHistory.shop_id == shop_id)
            .group_by(SearchHistory.search_term)
            .order_by(desc("count"))
            .limit(limit)
        )

        return [{"term": row.search_term, "count": row.count} for row in result]

    async def get_activity_log(self, user_id: uuid.UUID, limit: int = 20) -> List[ActivityLog]:
        """Get recent activity logs."""
        result = await self.db.execute(
            select(ActivityLog)
            .where(ActivityLog.user_id == user_id)
            .order_by(desc(ActivityLog.created_at))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_top_reviews(self, user_id: uuid.UUID, limit: int = 5) -> List[dict]:
        """Get top recent product reviews for the shop's menu items."""
        from app.models.review import MenuItemReview
        shop_id = await self._get_shop_id(user_id)

        result = await self.db.execute(
            select(MenuItemReview, MenuItem.name.label("item_name"))
            .join(MenuItem, MenuItem.id == MenuItemReview.menu_item_id)
            .where(MenuItemReview.shop_id == shop_id)
            .order_by(desc(MenuItemReview.rating), desc(MenuItemReview.created_at))
            .limit(limit)
        )
        
        reviews = []
        for review, item_name in result:
            reviews.append({
                "id": str(review.id),
                "item_name": item_name,
                "reviewer_name": review.reviewer_name or "Anonymous",
                "rating": review.rating,
                "comment": review.comment,
                "created_at": review.created_at.strftime("%b %d, %Y")
            })
        return reviews

    # ── Admin Stats ───────────────────────────────────────────

    async def get_platform_stats(self) -> dict:
        """Get platform-wide statistics (admin only)."""
        from app.models.user import User

        users = await self.db.execute(select(func.count(User.id)))
        shops = await self.db.execute(select(func.count(Shop.id)))
        scans = await self.db.execute(select(func.count(QRScan.id)))
        views = await self.db.execute(select(func.count(MenuView.id)))

        return {
            "total_users": users.scalar() or 0,
            "total_restaurants": shops.scalar() or 0,
            "total_qr_scans": scans.scalar() or 0,
            "total_menu_views": views.scalar() or 0,
        }
