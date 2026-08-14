"""Settlements API endpoints."""

from typing import Optional, List
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.database.session import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.shop import Shop
from app.models.shop_settings import ShopSettings
from app.models.order import Order
from app.models.contest import Contest, ContestParticipation
from sqlalchemy import func


router = APIRouter(prefix="/settlements", tags=["Settlements"])


class SettlementItemSchema(BaseModel):
    order_id: str
    invoice_no: str
    payment_reference: str
    payment_method: str
    customer_name: str
    customer_phone: Optional[str] = None
    gross_amount: float
    platform_fee: float
    net_settlement_amount: float
    order_status: str
    payment_status: str
    settlement_status: str  # "settled" or "pending"
    created_at: str
    estimated_payout_date: str


class SettlementSummaryResponse(BaseModel):
    total_online_sales: float
    total_settled_amount: float
    total_pending_settlement: float
    total_transactions_count: int
    settled_count: int
    pending_count: int
    bank_account_last4: Optional[str] = None
    settlement_policy_notice: str
    contest_participants_count: int = 0
    contest_settlement_amount: float = 0.0
    settlements: List[SettlementItemSchema] = []


@router.get("/me", response_model=SettlementSummaryResponse)
async def get_settlements_summary(
    days: int = 30,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    status_filter: Optional[str] = Query("all"),  # all, settled, pending
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get merchant online payment settlements summary and transaction list."""
    shop_q = await db.execute(select(Shop).where(Shop.user_id == user.id))
    shop = shop_q.scalars().first()
    if not shop:
        return SettlementSummaryResponse(
            total_online_sales=0.0,
            total_settled_amount=0.0,
            total_pending_settlement=0.0,
            total_transactions_count=0,
            settled_count=0,
            pending_count=0,
            bank_account_last4=None,
            settlement_policy_notice="Online payment amounts will be settled within 7 working days to your registered bank account or UPI ID.",
            settlements=[]
        )

    settings_q = await db.execute(select(ShopSettings).where(ShopSettings.shop_id == shop.id))
    settings = settings_q.scalars().first()
    payout_bank = shop.settings.bank_account_last4 if shop.settings else None

    now = datetime.now(timezone.utc)

    if start_date and end_date:
        try:
            since = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            until = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
        except ValueError:
            since = now - timedelta(days=days)
            until = now
    else:
        since = now - timedelta(days=days)
        until = now

    orders_q = await db.execute(
        select(Order)
        .where(
            Order.shop_id == shop.id,
            Order.created_at >= since,
            Order.created_at <= until,
            Order.order_status.notin_(["rejected", "cancelled"]),
            Order.payment_method == "online",
            Order.payment_status == "paid"
        )
        .order_by(desc(Order.created_at))
    )
    all_orders = list(orders_q.scalars().all())

    settlements_list = []
    total_online_sales = 0.0
    total_settled_amount = 0.0
    total_pending_settlement = 0.0
    settled_count = 0
    pending_count = 0

    for o in all_orders:
        gross = float(o.total_amount or 0.0)
        
        # Breakdown: 1% Gateway Route Fee
        gateway_fee = round(gross * 0.01, 2)
        total_fee = gateway_fee
        net = round(gross - total_fee, 2)

        created_dt = o.created_at if o.created_at.tzinfo else o.created_at.replace(tzinfo=timezone.utc)
        est_payout_dt = created_dt + timedelta(days=7)
        
        # Use real database settlement status if available, fallback to 7 days logic
        settlement_status = o.settlement_status or ("settled" if now >= est_payout_dt else "pending")
        is_settled = settlement_status == "settled"

        if status_filter and status_filter != "all":
            if status_filter == "settled" and not is_settled:
                continue
            if status_filter == "pending" and is_settled:
                continue

        total_online_sales += gross
        if is_settled:
            total_settled_amount += net
            settled_count += 1
        else:
            total_pending_settlement += net
            pending_count += 1

        inv_no = f"SETTL-{created_dt.strftime('%Y%m%d')}-{str(o.id)[:6].upper()}"
        pay_ref = o.cashfree_order_id or o.payment_session_id or f"TXN-{str(o.id)[:8].upper()}"
        
        pm = (o.payment_method or "").lower()

        settlements_list.append(SettlementItemSchema(
            order_id=str(o.id),
            invoice_no=inv_no,
            payment_reference=pay_ref,
            payment_method=pm or "online",
            customer_name=o.customer_name or "Customer",
            customer_phone=o.customer_phone or "",
            gross_amount=round(gross, 2),
            platform_fee=total_fee,
            net_settlement_amount=net,
            order_status=o.order_status,
            payment_status=o.payment_status,
            settlement_status=settlement_status,
            created_at=created_dt.strftime("%b %d, %Y %I:%M %p"),
            estimated_payout_date=est_payout_dt.strftime("%b %d, %Y")
        ))

    # Calculate contest settlements (only count successfully submitted entries)
    contest_q = await db.execute(
        select(func.count(ContestParticipation.id))
        .join(Contest, Contest.id == ContestParticipation.contest_id)
        .where(
            Contest.shop_id == shop.id,
            ContestParticipation.is_submitted == True,
            ContestParticipation.created_at >= since,
            ContestParticipation.created_at <= until
        )
    )
    contest_participants_count = contest_q.scalar() or 0
    contest_settlement_amount = round(contest_participants_count * 2.0, 2)

    return SettlementSummaryResponse(
        total_online_sales=round(total_online_sales, 2),
        total_settled_amount=round(total_settled_amount, 2),
        total_pending_settlement=round(total_pending_settlement, 2),
        total_transactions_count=len(settlements_list),
        settled_count=settled_count,
        pending_count=pending_count,
        bank_account_last4=payout_bank,
        settlement_policy_notice="Online payment amounts will be settled within 7 working days to your registered bank account.",
        contest_participants_count=contest_participants_count,
        contest_settlement_amount=contest_settlement_amount,
        settlements=settlements_list
    )
