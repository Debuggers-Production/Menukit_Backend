"""Broadcast campaign service for WhatsApp marketing."""

import uuid
from datetime import datetime, timezone, timedelta, time
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy import select, func, distinct, update, or_


from sqlalchemy.ext.asyncio import AsyncSession

from app.models.broadcast import BroadcastCampaign
from app.models.customer import Customer
from app.models.membership import CustomerRetailerMembership
from app.models.analytics import MembershipEvent
from app.models.order import Order
from app.models.shop import Shop
from app.models.theme_settings import ThemeSettings
from app.services.whatsapp_service import WhatsAppClient


class BroadcastService:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _normalize_phone(val: Any) -> Optional[str]:
        p = "".join(filter(str.isdigit, str(val or "")))
        if len(p) == 10:
            return f"91{p}"
        elif len(p) >= 11:
            return p
        return None

    async def get_target_audience_recipients(
        self,
        shop_id: uuid.UUID,
        target_audience: str = "all",
        min_visits: int = 2,
    ) -> List[Dict[str, str]]:
        """
        Fetch distinct target customer recipients with name and valid mobile number.
        Segments:
          - 'all': All customers with registered membership at this shop
          - 'new': Members registered in the last 7 days
          - 'min_visits': Members with at least `min_visits` visits/orders at this shop
        """
        recipients_map: Dict[str, str] = {}  # phone -> name

        if target_audience == "min_visits":
            # 1. Distinct event dates at this shop for registered members
            event_subq = (
                select(
                    Customer.mobile_number,
                    Customer.name,
                )
                .join(CustomerRetailerMembership, CustomerRetailerMembership.customer_id == Customer.id)
                .join(MembershipEvent, MembershipEvent.customer_id == Customer.id)
                .where(
                    CustomerRetailerMembership.shop_id == shop_id,
                    MembershipEvent.shop_id == shop_id,
                    MembershipEvent.event_type.in_(["member_matched", "otp_verified", "token_verified", "discount_unlocked"])
                )
                .group_by(Customer.id, Customer.mobile_number, Customer.name)
                .having(func.count(func.distinct(func.date(MembershipEvent.event_time))) >= min_visits)
            )
            res = await self.db.execute(event_subq)
            for row in res.all():
                phone = self._normalize_phone(row[0])
                if phone:
                    recipients_map[phone] = row[1] or "Customer"

            # 2. Also check if member has placed >= min_visits orders at this shop
            member_stmt = (
                select(Customer.mobile_number, Customer.name)
                .join(CustomerRetailerMembership, CustomerRetailerMembership.customer_id == Customer.id)
                .where(CustomerRetailerMembership.shop_id == shop_id)
            )
            m_res = await self.db.execute(member_stmt)
            for m_row in m_res.all():
                clean_p = self._normalize_phone(m_row[0])
                if clean_p and clean_p not in recipients_map:
                    # Check order count for this member
                    last10 = clean_p[-10:]
                    o_cnt_stmt = select(func.count(Order.id)).where(
                        Order.shop_id == shop_id,
                        Order.customer_phone.ilike(f"%{last10}%")
                    )
                    o_cnt_res = await self.db.execute(o_cnt_stmt)
                    if (o_cnt_res.scalar() or 0) >= min_visits:
                        recipients_map[clean_p] = m_row[1] or "Customer"

        elif target_audience == "new":
            seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
            stmt = (
                select(Customer.mobile_number, Customer.name)
                .join(CustomerRetailerMembership, CustomerRetailerMembership.customer_id == Customer.id)
                .where(
                    CustomerRetailerMembership.shop_id == shop_id,
                    CustomerRetailerMembership.created_at >= seven_days_ago
                )
            )
            res = await self.db.execute(stmt)
            for row in res.all():
                phone = self._normalize_phone(row[0])
                if phone:
                    recipients_map[phone] = row[1] or "Customer"

        else:
            # 'all' registered members of this shop
            stmt = (
                select(Customer.mobile_number, Customer.name)
                .join(CustomerRetailerMembership, CustomerRetailerMembership.customer_id == Customer.id)
                .where(CustomerRetailerMembership.shop_id == shop_id)
            )
            res = await self.db.execute(stmt)
            for row in res.all():
                phone = self._normalize_phone(row[0])
                if phone:
                    recipients_map[phone] = row[1] or "Customer"

        return [{"phone": phone, "name": name} for phone, name in recipients_map.items()]


    async def calculate_audience_count(
        self,
        shop_id: uuid.UUID,
        target_audience: str = "all",
        min_visits: int = 2
    ) -> int:
        recipients = await self.get_target_audience_recipients(shop_id, target_audience, min_visits)
        return len(recipients)

    async def get_shop_default_banner(self, shop_id: uuid.UUID) -> str:
        """Fetch shop theme banner or fallback image."""
        stmt = select(ThemeSettings.banner_style, ThemeSettings.primary_color).where(ThemeSettings.shop_id == shop_id)
        res = await self.db.execute(stmt)
        theme = res.first()
        # Fallback high quality food banner
        return "https://images.unsplash.com/photo-1555396273-367ea4eb4db5?fm=jpg&w=800&q=90"

    async def create_campaign(
        self,
        shop_id: uuid.UUID,
        title: str,
        message: str,
        image_url: Optional[str] = None,
        target_audience: str = "all",
        min_visits: Optional[int] = 2,
        scheduled_at: Optional[datetime] = None,
    ) -> BroadcastCampaign:
        """Create a campaign with credit validation, and either dispatch immediately or schedule."""
        recipients = await self.get_target_audience_recipients(shop_id, target_audience, min_visits or 2)
        total_recipients = len(recipients)

        # Check broadcast messaging credits balance (1 credit = 1 message = 1 INR)
        shop_stmt = select(Shop).where(Shop.id == shop_id)
        shop_res = await self.db.execute(shop_stmt)
        shop_obj = shop_res.scalar_one_or_none()
        available_credits = (shop_obj.broadcast_credits if shop_obj else 0) or 0

        if total_recipients > available_credits:
            raise ValueError(f"INSUFFICIENT_CREDITS:{total_recipients}:{available_credits}")

        # Deduct credits immediately on campaign launch
        if shop_obj and total_recipients > 0:
            shop_obj.broadcast_credits = max(0, available_credits - total_recipients)

        status = "SCHEDULED" if scheduled_at and scheduled_at > datetime.now(timezone.utc) else "PROCESSING"

        campaign = BroadcastCampaign(
            shop_id=shop_id,
            title=title,
            message=message,
            image_url=image_url,
            target_audience=target_audience,
            min_visits=min_visits if target_audience == "min_visits" else None,
            status=status,
            scheduled_at=scheduled_at,
            total_recipients=total_recipients,
            sent_count=0,
            failed_count=0,
        )
        self.db.add(campaign)
        await self.db.commit()
        await self.db.refresh(campaign)

        if status == "PROCESSING":
            # Trigger immediate delivery in background
            import asyncio
            asyncio.create_task(self._send_broadcast_now(campaign.id))

        return campaign

    async def send_test_message(
        self,
        shop_id: uuid.UUID,
        phone_number: str,
        message: str,
        image_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a single test campaign message to the merchant's test number (costs 1 credit)."""
        shop_stmt = select(Shop).where(Shop.id == shop_id)
        shop_res = await self.db.execute(shop_stmt)
        shop_obj = shop_res.scalar_one_or_none()
        available_credits = (shop_obj.broadcast_credits if shop_obj else 0) or 0

        if available_credits < 1:
            raise ValueError("INSUFFICIENT_CREDITS:1:0")

        shop_name = (shop_obj.name if shop_obj else None) or "Restaurant"

        wa = WhatsAppClient()
        final_image = image_url if image_url and image_url.strip() else await self.get_shop_default_banner(shop_id)

        res = wa.send_user_campaign_template(
            phone_number=phone_number,
            customer_name="Valued Customer",
            shop_name=shop_name,
            custom_message=message,
            shop_id=str(shop_id),
            header_image_url=final_image,
        )

        # Deduct 1 credit for the test message
        if shop_obj:
            shop_obj.broadcast_credits = max(0, available_credits - 1)
            await self.db.commit()

        return res


    async def _send_broadcast_now(self, campaign_id: uuid.UUID):
        """Worker background task to iterate through recipients, dispatch WhatsApp templates, and refund failed credits."""
        from app.database.session import async_session_factory
        async with async_session_factory() as session:
            c_stmt = select(BroadcastCampaign).where(BroadcastCampaign.id == campaign_id)
            res = await session.execute(c_stmt)
            campaign = res.scalar_one_or_none()
            if not campaign or campaign.status in ("SENT", "PARTIAL", "CANCELLED"):
                return

            shop_stmt = select(Shop).where(Shop.id == campaign.shop_id)
            shop_res = await session.execute(shop_stmt)
            shop_obj = shop_res.scalar_one_or_none()
            shop_name = (shop_obj.name if shop_obj else None) or "Restaurant"

            b_service = BroadcastService(session)
            recipients = await b_service.get_target_audience_recipients(
                campaign.shop_id, campaign.target_audience, campaign.min_visits or 2
            )

            final_image = campaign.image_url if campaign.image_url and campaign.image_url.strip() else await b_service.get_shop_default_banner(campaign.shop_id)

            import concurrent.futures
            wa = WhatsAppClient()

            def send_one(recipient):
                try:
                    res = wa.send_user_campaign_template(
                        phone_number=recipient["phone"],
                        customer_name=recipient["name"],
                        shop_name=shop_name,
                        custom_message=campaign.message,
                        shop_id=str(campaign.shop_id),
                        header_image_url=final_image,
                    )
                    if isinstance(res, dict) and ("messages" in res or "id" in res):
                        return True
                    return False
                except Exception as ex:
                    print(f"Broadcast recipient {recipient['phone']} failed: {ex}")
                    return False

            sent_count = 0
            failed_count = 0

            try:
                # Execute concurrently with parallel workers
                import asyncio
                loop = asyncio.get_running_loop()
                with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                    futures = [loop.run_in_executor(executor, send_one, r) for r in recipients]
                    results = await asyncio.gather(*futures, return_exceptions=True)

                for r in results:
                    if r is True:
                        sent_count += 1
                    else:
                        failed_count += 1
            except Exception as loop_ex:
                print(f"Broadcast background task exception: {loop_ex}")
                unprocessed = max(0, len(recipients) - (sent_count + failed_count))
                failed_count += unprocessed

            # Set status: SENT if all succeeded, PARTIAL if some succeeded & some failed, FAILED if none succeeded
            if sent_count > 0 and failed_count > 0:
                campaign.status = "PARTIAL"
            elif sent_count > 0 or len(recipients) == 0:
                campaign.status = "SENT"
            else:
                campaign.status = "FAILED"

            campaign.sent_count = sent_count
            campaign.failed_count = failed_count
            campaign.sent_at = datetime.now(timezone.utc)

            # If any messages failed, refund the unused credits back to the merchant's balance
            if shop_obj and failed_count > 0:
                shop_obj.broadcast_credits = (shop_obj.broadcast_credits or 0) + failed_count
                print(f"Refunded {failed_count} broadcast credits to shop {shop_obj.name} (failed deliveries)")

            await session.commit()






    async def list_campaigns(
        self,
        shop_id: uuid.UUID,
        search: Optional[str] = None,
        date_filter: Optional[str] = None,
        page: int = 1,
        page_size: int = 15,
    ) -> Tuple[List[BroadcastCampaign], int]:
        stmt = select(BroadcastCampaign).where(BroadcastCampaign.shop_id == shop_id)
        count_stmt = select(func.count(BroadcastCampaign.id)).where(BroadcastCampaign.shop_id == shop_id)

        if search and search.strip():
            term = f"%{search.strip()}%"
            filter_clause = or_(
                BroadcastCampaign.title.ilike(term),
                BroadcastCampaign.message.ilike(term),
                BroadcastCampaign.target_audience.ilike(term),
                BroadcastCampaign.status.ilike(term),
            )
            stmt = stmt.where(filter_clause)
            count_stmt = count_stmt.where(filter_clause)

        if date_filter and date_filter.strip():
            try:
                # Expect YYYY-MM-DD
                d = datetime.strptime(date_filter.strip(), "%Y-%m-%d").date()
                start_dt = datetime.combine(d, time.min).replace(tzinfo=timezone.utc) - timedelta(hours=6)
                end_dt = datetime.combine(d, time.max).replace(tzinfo=timezone.utc) + timedelta(hours=6)
                date_clause = or_(
                    func.date(BroadcastCampaign.created_at) == d,
                    (BroadcastCampaign.created_at >= start_dt) & (BroadcastCampaign.created_at <= end_dt)
                )
                stmt = stmt.where(date_clause)
                count_stmt = count_stmt.where(date_clause)
            except ValueError:
                pass


        total_res = await self.db.execute(count_stmt)
        total = total_res.scalar() or 0

        skip = max(0, (page - 1) * page_size)
        stmt = stmt.order_by(BroadcastCampaign.created_at.desc()).offset(skip).limit(page_size)
        res = await self.db.execute(stmt)
        items = list(res.scalars().all())

        return items, total


    async def cancel_campaign(self, shop_id: uuid.UUID, campaign_id: uuid.UUID) -> bool:
        stmt = (
            select(BroadcastCampaign)
            .where(BroadcastCampaign.id == campaign_id, BroadcastCampaign.shop_id == shop_id)
        )
        res = await self.db.execute(stmt)
        campaign = res.scalar_one_or_none()
        if not campaign or campaign.status == "SENT":
            return False
        await self.db.delete(campaign)
        await self.db.commit()
        return True

    async def get_media_library(self, shop_id: uuid.UUID) -> List[str]:
        """Fetch distinct previous campaign image URLs for this shop (max 4)."""
        stmt = (
            select(BroadcastCampaign.image_url)
            .where(
                BroadcastCampaign.shop_id == shop_id,
                BroadcastCampaign.image_url.is_not(None),
                BroadcastCampaign.image_url != ""
            )
            .group_by(BroadcastCampaign.image_url)
            .order_by(func.max(BroadcastCampaign.created_at).desc())
            .limit(4)
        )
        res = await self.db.execute(stmt)
        return [row[0] for row in res.all() if row[0]]


    async def delete_media_image(self, shop_id: uuid.UUID, image_url: str) -> bool:
        """Delete image from MinIO/disk and clear campaign references for this shop."""
        from app.services.upload_service import UploadService
        upload_service = UploadService()
        await upload_service.delete_image_by_url(image_url)

        # Clear image_url from campaign history so it is removed from the library
        stmt = (
            update(BroadcastCampaign)
            .where(BroadcastCampaign.shop_id == shop_id, BroadcastCampaign.image_url == image_url)
            .values(image_url=None)
        )
        await self.db.execute(stmt)
        await self.db.commit()
        return True

