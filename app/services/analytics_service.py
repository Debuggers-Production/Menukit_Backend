"""Analytics service for tracking and reporting."""

import uuid
import asyncio
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
        if ip:
            # Check if this IP scanned this shop in the last 24 hours
            since = datetime.now(timezone.utc) - timedelta(hours=24)
            recent_scan = await self.db.execute(
                select(QRScan.id)
                .where(QRScan.shop_id == shop_id, QRScan.ip_address == ip, QRScan.scanned_at >= since)
                .limit(1)
            )
            if recent_scan.scalar_one_or_none():
                return  # Skip recording to prevent spam from refreshes

        scan = QRScan(shop_id=shop_id, ip_address=ip, user_agent=ua, referrer=ref)
        self.db.add(scan)
        await self.db.flush()

    async def record_menu_view(
        self, shop_id: uuid.UUID, item_id: uuid.UUID = None, category_id: uuid.UUID = None, ip: str = None
    ):
        """Record a menu page/item view."""
        if ip:
            # Check if this IP viewed this specific item/category in the last 24 hours
            since = datetime.now(timezone.utc) - timedelta(hours=24)
            query = select(MenuView.id).where(
                MenuView.shop_id == shop_id, 
                MenuView.ip_address == ip, 
                MenuView.viewed_at >= since
            )
            
            if item_id:
                query = query.where(MenuView.menu_item_id == item_id)
            elif category_id:
                query = query.where(MenuView.category_id == category_id)
            else:
                # Top level menu view
                query = query.where(MenuView.menu_item_id.is_(None), MenuView.category_id.is_(None))
                
            recent_view = await self.db.execute(query.limit(1))
            if recent_view.scalar_one_or_none():
                return  # Skip recording to prevent spam

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
        """Get dashboard overview statistics (parallel queries via asyncio.gather)."""
        shop_id = await self._get_shop_id(user_id)

        items_res = await self.db.execute(
            select(func.count(MenuItem.id)).where(MenuItem.shop_id == shop_id)
        )
        cats_res = await self.db.execute(
            select(func.count(Category.id)).where(Category.shop_id == shop_id)
        )
        scans_res = await self.db.execute(
            select(func.count(QRScan.id)).where(QRScan.shop_id == shop_id)
        )
        views_res = await self.db.execute(
            select(func.count(MenuView.id)).where(MenuView.shop_id == shop_id)
        )

        return {
            "total_menu_items": items_res.scalar() or 0,
            "total_categories": cats_res.scalar() or 0,
            "total_qr_scans": scans_res.scalar() or 0,
            "total_menu_views": views_res.scalar() or 0,
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

    async def get_daily_report(self, user_id: uuid.UUID, target_date: str) -> dict:
        """Get daily report statistics for a specific date (YYYY-MM-DD)."""
        shop_id = await self._get_shop_id(user_id)
        # Parse target date
        try:
            target_dt = datetime.strptime(target_date, "%Y-%m-%d").date()
        except ValueError:
            raise ValueError("Invalid date format. Expected YYYY-MM-DD")

        # Scans on target_date
        scans_res = await self.db.execute(
            select(func.count(QRScan.id)).where(
                QRScan.shop_id == shop_id,
                func.date(QRScan.scanned_at) == target_dt
            )
        )
        
        # Views on target_date
        views_res = await self.db.execute(
            select(func.count(MenuView.id)).where(
                MenuView.shop_id == shop_id,
                func.date(MenuView.viewed_at) == target_dt
            )
        )
        
        # Searches on target_date
        searches_res = await self.db.execute(
            select(func.count(SearchHistory.id)).where(
                SearchHistory.shop_id == shop_id,
                func.date(SearchHistory.searched_at) == target_dt
            )
        )
        
        total_scans = scans_res.scalar() or 0
        total_views = views_res.scalar() or 0
        total_searches = searches_res.scalar() or 0
        
        # Top items on target_date
        top_items_res = await self.db.execute(
            select(MenuItem.name, func.count(MenuView.id).label("count"))
            .join(MenuView, MenuView.menu_item_id == MenuItem.id)
            .where(
                MenuView.shop_id == shop_id, 
                MenuView.menu_item_id.isnot(None),
                func.date(MenuView.viewed_at) == target_dt
            )
            .group_by(MenuItem.name)
            .order_by(desc("count"))
            .limit(5)
        )
        top_items = [{"name": row.name, "count": row.count} for row in top_items_res]
        
        # Repeated customers on target_date
        # Customers who visited on this date AND have overall visit_count >= 2
        from app.models.analytics import MembershipEvent
        
        # Subquery: get total visit count per customer
        visit_count_subq = (
            select(
                MembershipEvent.customer_id,
                func.count(func.distinct(func.date(MembershipEvent.event_time))).label("visit_count")
            )
            .where(
                MembershipEvent.shop_id == shop_id,
                MembershipEvent.event_type.in_(["member_matched", "otp_verified", "token_verified", "discount_unlocked"])
            )
            .group_by(MembershipEvent.customer_id)
            .subquery()
        )
        # Top searches on target_date
        top_searches_res = await self.db.execute(
            select(SearchHistory.search_term, func.count(SearchHistory.id).label("count"))
            .where(
                SearchHistory.shop_id == shop_id,
                func.date(SearchHistory.searched_at) == target_dt
            )
            .group_by(SearchHistory.search_term)
            .order_by(desc("count"))
            .limit(10)
        )
        top_searches = [{"term": row.search_term, "count": row.count} for row in top_searches_res]

        # Query: distinct customers who visited on target_date AND visit_count >= 2
        from app.models.customer import Customer
        repeated_customers_res = await self.db.execute(
            select(Customer.name, Customer.mobile_number, visit_count_subq.c.visit_count)
            .join(visit_count_subq, visit_count_subq.c.customer_id == Customer.id)
            .join(MembershipEvent, MembershipEvent.customer_id == Customer.id)
            .where(
                MembershipEvent.shop_id == shop_id,
                MembershipEvent.event_type.in_(["member_matched", "otp_verified", "token_verified", "discount_unlocked"]),
                func.date(MembershipEvent.event_time) == target_dt,
                visit_count_subq.c.visit_count >= 2
            )
            .distinct()
        )
        repeated_customers_list = [
            {
                "name": row.name,
                "mobile_number": row.mobile_number,
                "visit_count": row.visit_count
            }
            for row in repeated_customers_res
        ]
        
        return {
            "date": target_date,
            "total_scans": total_scans,
            "total_views": total_views,
            "total_searches": total_searches,
            "repeated_customers_count": len(repeated_customers_list),
            "top_items": top_items,
            "top_searches": top_searches,
            "repeated_customers": repeated_customers_list
        }
