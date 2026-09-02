"""Settlements API endpoints."""

from typing import Optional, List
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, or_, and_, func, cast, String

from app.database.session import get_db
from app.core.deps import get_current_user, require_permission
from app.models.user import User
from app.models.shop import Shop
from app.models.shop_settings import ShopSettings
from app.models.order import Order
from app.models.contest import Contest, ContestParticipation


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
    actual_settled_date: Optional[str] = None


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
    has_more: bool = False
    skip: int = 0
    limit: int = 20
    settlements: List[SettlementItemSchema] = []


@router.get("/me", response_model=SettlementSummaryResponse)
async def get_settlements_summary(
    days: int = 30,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    status_filter: Optional[str] = Query("all"),  # all, settled, pending
    search: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    shop = Depends(require_permission("settlements", "read")),
    db: AsyncSession = Depends(get_db),
):
    """Get merchant online payment settlements summary and paginated transaction list with search."""

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

    cutoff_7d = now - timedelta(days=7)

    # Base filtering conditions
    base_conditions = [
        Order.shop_id == shop.id,
        Order.created_at >= since,
        Order.created_at <= until,
        Order.order_status.notin_(["rejected", "cancelled"]),
        Order.payment_method == "online",
        Order.payment_status == "paid"
    ]

    # Backend Search Filter
    if search and search.strip():
        term = f"%{search.strip()}%"
        base_conditions.append(
            or_(
                Order.customer_name.ilike(term),
                Order.customer_phone.ilike(term),
                cast(Order.id, String).ilike(term),
                Order.cashfree_order_id.ilike(term),
                Order.payment_session_id.ilike(term)
            )
        )

    # Status Filter
    settled_condition = or_(
        Order.settlement_status == "settled",
        and_(Order.settlement_status.is_(None), Order.created_at <= cutoff_7d)
    )
    pending_condition = or_(
        Order.settlement_status == "pending",
        and_(Order.settlement_status.is_(None), Order.created_at > cutoff_7d)
    )

    if status_filter == "settled":
        base_conditions.append(settled_condition)
    elif status_filter == "pending":
        base_conditions.append(pending_condition)

    # Calculate Totals & Counts
    total_count_q = await db.execute(select(func.count(Order.id)).where(*base_conditions))
    total_transactions_count = total_count_q.scalar() or 0

    total_gross_q = await db.execute(select(func.coalesce(func.sum(Order.total_amount), 0.0)).where(*base_conditions))
    total_online_sales = float(total_gross_q.scalar() or 0.0)

    # Settled & Pending Counts and Amounts
    settled_q = await db.execute(
        select(func.count(Order.id), func.coalesce(func.sum(Order.total_amount), 0.0))
        .where(*base_conditions, settled_condition)
    )
    settled_res = settled_q.first()
    settled_count = settled_res[0] or 0
    settled_gross = float(settled_res[1] or 0.0)
    total_settled_amount = round(settled_gross, 2)  # 100% net to vendor (0% fee)

    pending_q = await db.execute(
        select(func.count(Order.id), func.coalesce(func.sum(Order.total_amount), 0.0))
        .where(*base_conditions, pending_condition)
    )
    pending_res = pending_q.first()
    pending_count = pending_res[0] or 0
    pending_gross = float(pending_res[1] or 0.0)
    total_pending_settlement = round(pending_gross, 2)  # 100% net to vendor (0% fee)

    # Paginated Orders Retrieval
    orders_q = await db.execute(
        select(Order)
        .where(*base_conditions)
        .order_by(desc(Order.created_at))
        .offset(skip)
        .limit(limit)
    )
    paginated_orders = list(orders_q.scalars().all())

    settlements_list = []
    for o in paginated_orders:
        gross = float(o.total_amount or 0.0)
        gateway_fee = 0.0
        total_fee = 0.0
        net = round(gross, 2)


        created_dt = o.created_at if o.created_at.tzinfo else o.created_at.replace(tzinfo=timezone.utc)
        est_payout_dt = created_dt + timedelta(days=7)
        
        settlement_status = o.settlement_status or ("settled" if now >= est_payout_dt else "pending")
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
            estimated_payout_date=est_payout_dt.strftime("%b %d, %Y"),
            actual_settled_date=o.settled_at.strftime("%b %d, %Y") if o.settled_at else None
        ))

    # Calculate contest settlements
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

    has_more = (skip + len(paginated_orders)) < total_transactions_count

    return SettlementSummaryResponse(
        total_online_sales=round(total_online_sales, 2),
        total_settled_amount=round(total_settled_amount, 2),
        total_pending_settlement=round(total_pending_settlement, 2),
        total_transactions_count=total_transactions_count,
        settled_count=settled_count,
        pending_count=pending_count,
        bank_account_last4=payout_bank,
        settlement_policy_notice="Online payment amounts will be settled within 7 working days to your registered bank account.",
        contest_participants_count=contest_participants_count,
        contest_settlement_amount=contest_settlement_amount,
        has_more=has_more,
        skip=skip,
        limit=limit,
        settlements=settlements_list
    )
