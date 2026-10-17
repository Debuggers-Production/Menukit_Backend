"""Scheduled notification service for automated email triggers.

1. New Order Email to Admin (real-time order event)
2. Subscription Expiry Checks:
   - 3 days before expiration: alert sent to admin
   - After expiration: alert sent every 2 days
3. Weekend Customer Digest:
   - Every weekend: total customer count report sent to admin
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
import pytz
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

import calendar
from app.models.shop import Shop
from app.models.user import User
from app.models.subscription import Subscription
from app.models.membership import CustomerRetailerMembership
from app.models.order import Order
from app.models.scheme import Scheme, SchemeMember
from app.services.email_service import email_service
from app.services.whatsapp_service import WhatsAppClient
from app.core.config import get_settings
from app.database.redis import get_redis

logger = logging.getLogger(__name__)
settings = get_settings()


class ScheduledNotificationService:
    """Automated notification scheduler service."""

    @staticmethod
    def _get_recipients(shop: Shop, user: Optional[User] = None) -> List[str]:
        """Collect shop owner email and optional admin notification email."""
        recipients = set()
        owner_email = None

        if user and user.email:
            owner_email = user.email
        elif hasattr(shop, "user") and shop.user and shop.user.email:
            owner_email = shop.user.email

        if owner_email and "@" in str(owner_email):
            recipients.add(str(owner_email).strip().lower())

        admin_email = getattr(settings, "ADMIN_NOTIFICATION_EMAIL", None)
        if admin_email and "@" in str(admin_email):
            recipients.add(str(admin_email).strip().lower())

        return list(recipients)

    @staticmethod
    async def process_subscription_expiry_checks(db: AsyncSession) -> Dict[str, Any]:
        """Check all shops and trigger subscription expiry emails:

        - 3 days before expiration (warning email to admin)
        - After expiration: every 2 days (expired notice to admin)
        """
        now = datetime.now(timezone.utc)
        today_str = now.strftime("%Y-%m-%d")
        redis_client = await get_redis()

        stmt = select(Subscription, Shop, User).join(
            Shop, Subscription.shop_id == Shop.id
        ).join(
            User, Shop.user_id == User.id
        )
        results = await db.execute(stmt)
        rows = results.all()

        expiring_soon_sent = 0
        expired_sent = 0

        for sub, shop, user in rows:
            # 1. Determine effective expiration date
            expiry_dt = sub.current_period_end
            expiring_modules = []
            expired_modules = []

            # Check individual module expirations if present
            raw_expirations = dict(getattr(sub, "module_expirations", {}) or {})
            min_days_left = 9999

            if raw_expirations:
                for mod_id, exp_val in raw_expirations.items():
                    if not exp_val:
                        continue
                    try:
                        m_dt = datetime.fromisoformat(str(exp_val).replace("Z", "+00:00"))
                        if m_dt.tzinfo is None:
                            m_dt = m_dt.replace(tzinfo=timezone.utc)
                        d_left = (m_dt - now).total_seconds() / 86400.0

                        if 0 <= d_left <= 3.0:
                            expiring_modules.append(mod_id)
                            min_days_left = min(min_days_left, int(d_left))
                        elif d_left < 0:
                            expired_modules.append(mod_id)
                    except Exception:
                        pass
            elif expiry_dt:
                if expiry_dt.tzinfo is None:
                    expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
                d_left = (expiry_dt - now).total_seconds() / 86400.0
                if 0 <= d_left <= 3.0:
                    expiring_modules.append("SmartMenu Full Plan")
                    min_days_left = max(0, int(d_left))
                elif d_left < 0:
                    expired_modules.append("SmartMenu Full Plan")

            recipients = ScheduledNotificationService._get_recipients(shop, user)
            if not recipients:
                continue

            # CASE A: Subscription / Modules Expiring in <= 3 Days
            if expiring_modules:
                cache_key = f"sub_warn_3d:{shop.id}:{today_str}"
                already_sent_today = False
                if redis_client:
                    try:
                        already_sent_today = bool(await redis_client.get(cache_key))
                    except Exception:
                        pass

                if not already_sent_today and sub.last_expiry_notification_date != today_str:
                    for recipient in recipients:
                        await email_service.send_subscription_expiring_email(
                            email=recipient,
                            shop_name=shop.name,
                            min_days=max(0, min_days_left if min_days_left != 9999 else 3),
                            expiring_modules=expiring_modules
                        )
                    sub.last_expiry_notification_date = today_str
                    if redis_client:
                        try:
                            await redis_client.set(cache_key, "1", ex=86400)
                        except Exception:
                            pass
                    expiring_soon_sent += 1

            # CASE B: Subscription / Modules Expired or Due for Renewal
            elif expired_modules:
                # If Auto-Renew is enabled, automatically renew the subscription for the next cycle
                if getattr(sub, "auto_renew", True):
                    cycle = getattr(sub, "billing_cycle", "monthly") or "monthly"
                    duration_days = 365 if cycle == "yearly" else 30
                    new_period_end = now + timedelta(days=duration_days)

                    from app.api.v1.subscription import ALL_MARKETPLACE_MODULES
                    from app.models.subscription import PaymentTransaction
                    from app.services.invoice_service import InvoiceService
                    import uuid

                    active_mods = list(sub.active_modules or [])
                    if not active_mods and getattr(sub, "is_all_access", False):
                        active_mods = list(ALL_MARKETPLACE_MODULES)

                    updated_exp = {mod_k: new_period_end.isoformat() for mod_k in active_mods}
                    sub.module_expirations = updated_exp
                    sub.current_period_end = new_period_end
                    sub.is_active = True
                    sub.is_trial = False

                    renewal_tx = PaymentTransaction(
                        shop_id=shop.id,
                        razorpay_order_id=f"order_autorenew_{uuid.uuid4().hex[:12]}",
                        razorpay_payment_id=f"pay_autorenew_{uuid.uuid4().hex[:12]}",
                        amount=0.0,
                        currency="INR",
                        status="success",
                        is_all_access=getattr(sub, "is_all_access", False),
                        purchased_modules=active_mods,
                        billing_cycle=cycle,
                        is_autopay=True
                    )
                    db.add(renewal_tx)
                    await db.flush()

                    inv_num = InvoiceService.generate_invoice_number(str(renewal_tx.id))
                    renewal_tx.invoice_number = inv_num

                    for recipient in recipients:
                        try:
                            inv_data = InvoiceService.build_invoice_data(
                                transaction=renewal_tx,
                                user_email=recipient,
                                shop_name=shop.name,
                                invoice_number=inv_num
                            )
                            await email_service.send_subscription_invoice_email(recipient, inv_data)
                        except Exception as em_err:
                            logger.warning(f"Failed to send auto-renewal invoice to {recipient}: {em_err}")

                    logger.info(f"Auto-renewed subscription for shop '{shop.name}' ({shop.id}) for {cycle} cycle ({duration_days} days).")
                    continue

                # If Auto-Renew is OFF: Alert Every 2 Days
                cache_key_last_sent = f"sub_expired_last_sent:{shop.id}"
                should_send_expired = False
                last_sent_iso = None

                if redis_client:
                    try:
                        last_sent_iso = await redis_client.get(cache_key_last_sent)
                    except Exception:
                        pass

                if not last_sent_iso:
                    should_send_expired = True
                else:
                    try:
                        last_dt = datetime.fromisoformat(str(last_sent_iso))
                        if (now - last_dt).total_seconds() >= (2 * 86400 - 300):  # Every 2 days
                            should_send_expired = True
                    except Exception:
                        should_send_expired = True

                if should_send_expired:
                    for recipient in recipients:
                        await email_service.send_subscription_expired_email(
                            email=recipient,
                            shop_name=shop.name,
                            expired_modules=expired_modules
                        )
                    if redis_client:
                        try:
                            await redis_client.set(cache_key_last_sent, now.isoformat(), ex=604800)
                        except Exception:
                            pass
                    expired_sent += 1

        await db.commit()
        return {
            "status": "success",
            "expiring_soon_sent": expiring_soon_sent,
            "expired_sent": expired_sent,
            "checked_at": today_str
        }

    @staticmethod
    async def process_weekend_customer_reports(db: AsyncSession, force: bool = False) -> Dict[str, Any]:
        """Trigger weekend email summary for total customer count.

        Triggers on weekends (Saturday / Sunday in IST).
        """
        ist_tz = pytz.timezone("Asia/Kolkata")
        now_ist = datetime.now(ist_tz)
        is_weekend = now_ist.weekday() in [5, 6]  # 5=Saturday, 6=Sunday

        if not is_weekend and not force:
            return {
                "status": "skipped",
                "message": f"Today is {now_ist.strftime('%A')}, reports are scheduled for weekends (Sat/Sun). Set force=true to run now."
            }

        weekend_key = f"{now_ist.year}-W{now_ist.isocalendar()[1]}"
        now_utc = datetime.now(timezone.utc)
        seven_days_ago = now_utc - timedelta(days=7)
        redis_client = await get_redis()

        # Query all active shops
        stmt = select(Shop).options(selectinload(Shop.user)).where(Shop.is_active == True)
        res = await db.execute(stmt)
        shops = res.scalars().all()

        reports_sent = 0

        for shop in shops:
            recipients = ScheduledNotificationService._get_recipients(shop)
            if not recipients:
                continue

            cache_key = f"weekend_customer_digest_sent:{shop.id}:{weekend_key}"
            if not force and redis_client:
                try:
                    already_sent = await redis_client.get(cache_key)
                    if already_sent:
                        continue
                except Exception:
                    pass

            # 1. Total customer count
            total_cust_res = await db.execute(
                select(func.count(CustomerRetailerMembership.id)).where(
                    CustomerRetailerMembership.shop_id == shop.id
                )
            )
            total_customers = total_cust_res.scalar() or 0

            # 2. New customers gained this week
            new_cust_res = await db.execute(
                select(func.count(CustomerRetailerMembership.id)).where(
                    CustomerRetailerMembership.shop_id == shop.id,
                    CustomerRetailerMembership.created_at >= seven_days_ago
                )
            )
            new_customers_this_week = new_cust_res.scalar() or 0

            # 3. Orders and revenue this week
            orders_res = await db.execute(
                select(
                    func.count(Order.id),
                    func.coalesce(func.sum(Order.total_amount), 0.0)
                ).where(
                    Order.shop_id == shop.id,
                    Order.created_at >= seven_days_ago,
                    func.lower(Order.order_status).notin_(["cancelled", "rejected"])
                )
            )
            orders_row = orders_res.first()
            orders_this_week = orders_row[0] if orders_row else 0
            revenue_this_week = float(orders_row[1]) if orders_row else 0.0

            weekend_label = f"Weekend Digest ({now_ist.strftime('%d %b %Y')})"

            for recipient in recipients:
                await email_service.send_weekend_customer_summary_email(
                    email=recipient,
                    shop_name=shop.name,
                    total_customers=total_customers,
                    new_customers_this_week=new_customers_this_week,
                    orders_this_week=orders_this_week,
                    revenue_this_week=revenue_this_week,
                    weekend_label=weekend_label
                )

            if redis_client:
                try:
                    await redis_client.set(cache_key, "1", ex=604800)  # 7 days expiry
                except Exception:
                    pass

            reports_sent += 1

        return {
            "status": "success",
            "weekend_key": weekend_key,
            "reports_sent": reports_sent
        }

    @staticmethod
    def _add_months(dt: datetime, n: int) -> datetime:
        """Add n months to dt, preserving day of month with month-end clipping."""
        month = dt.month - 1 + n
        year = dt.year + month // 12
        month = month % 12 + 1
        day = min(dt.day, calendar.monthrange(year, month)[1])
        return dt.replace(year=year, month=month, day=day)

    @staticmethod
    async def process_scheme_payment_reminders(db: AsyncSession, force: bool = False) -> Dict[str, Any]:
        """Trigger WhatsApp payment reminders 1 day before due date for Scheme members.

        For Monthly schemes:
          Reminder sent 1 day before monthly due date (e.g. joined on 15th -> reminder on 14th of next month).
        For Weekly schemes:
          Reminder sent on Day 6 (1 day before weekly due date on Day 7).
        """
        ist_tz = pytz.timezone("Asia/Kolkata")
        now_ist = datetime.now(ist_tz)
        today_date = now_ist.date()
        redis_client = await get_redis()
        whatsapp_client = WhatsAppClient()

        # Query all active scheme members where installments remain
        stmt = (
            select(SchemeMember)
            .options(
                selectinload(SchemeMember.scheme).selectinload(Scheme.shop).selectinload(Shop.settings),
            )
            .where(
                SchemeMember.status == "active",
                SchemeMember.paid_installments < SchemeMember.total_installments,
            )
        )
        results = await db.execute(stmt)
        members = results.scalars().all()

        reminders_sent = 0
        skipped_count = 0
        details = []

        for member in members:
            scheme = member.scheme
            if not scheme or scheme.status != "active":
                continue

            shop = getattr(scheme, "shop", None)
            if not shop or not shop.is_active:
                continue

            next_installment_num = member.paid_installments + 1
            if next_installment_num > member.total_installments:
                continue

            # Calculate installment due date in IST
            joined_at = member.joined_at
            if joined_at.tzinfo is None:
                joined_at = pytz.timezone("UTC").localize(joined_at)

            joined_at_ist = joined_at.astimezone(ist_tz)

            if scheme.frequency == "weekly":
                due_date_ist = joined_at_ist + timedelta(weeks=(next_installment_num - 1))
            else:
                due_date_ist = ScheduledNotificationService._add_months(joined_at_ist, next_installment_num - 1)

            # Reminder date is 1 day before due date
            reminder_date = (due_date_ist - timedelta(days=1)).date()
            due_date_str = due_date_ist.strftime("%d-%m-%Y")

            # Check if today is the reminder date (or force run)
            # Send when today matches reminder_date (or if force=True or within 1 day of due date)
            should_remind = force or (reminder_date <= today_date <= due_date_ist.date())

            if not should_remind:
                skipped_count += 1
                continue

            # Check deduplication via Redis
            cache_key = f"scheme_fund_reminder_sent:{member.id}:{next_installment_num}"
            if not force and redis_client:
                try:
                    already_sent = await redis_client.get(cache_key)
                    if already_sent:
                        skipped_count += 1
                        continue
                except Exception:
                    pass

            # Format amount with shop currency
            price = float(scheme.price)
            amount_str = f"{int(price)}" if price == int(price) else f"{price:.2f}"
            shop_settings = getattr(shop, "settings", None)
            currency = (shop_settings.currency if shop_settings and shop_settings.currency else "rs").strip()
            amount_with_currency = f"{amount_str} {currency}"

            try:
                wa_res = whatsapp_client.send_scheme_fund_reminder(
                    phone_number=member.customer_phone,
                    customer_name=member.customer_name,
                    scheme_title=scheme.title,
                    shop_name=shop.name,
                    due_date_str=due_date_str,
                    amount_with_currency=amount_with_currency,
                    shop_id=str(shop.id),
                )
                try:
                    logger.info(
                        f"[SCHEME_REMINDER] Sent to {member.customer_name} ({member.customer_phone}) "
                        f"for {scheme.title} (Inst. #{next_installment_num}, Due {due_date_str})"
                    )
                except Exception:
                    pass

                if redis_client:
                    try:
                        # 30 days TTL so it is never re-sent for this installment
                        await redis_client.set(cache_key, "1", ex=2592000)
                    except Exception:
                        pass

                reminders_sent += 1
                details.append({
                    "member_id": str(member.id),
                    "customer_name": member.customer_name,
                    "phone": member.customer_phone,
                    "scheme_title": scheme.title,
                    "installment_number": next_installment_num,
                    "due_date": due_date_str,
                    "amount": amount_with_currency,
                    "wa_response": wa_res,
                })
            except Exception as e:
                logger.error(f"[SCHEME_REMINDER] Failed for member {member.id}: {e}")

        return {
            "status": "success",
            "reminders_sent": reminders_sent,
            "skipped": skipped_count,
            "checked_at": today_date.strftime("%Y-%m-%d"),
            "details": details,
        }
