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
from app.models.scheme import Scheme, SchemeMember, SchemePayment


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
    """Get merchant online payment settlements summary and paginated transaction list with search,

    including both online orders and online scheme installment payments.
    """

    # Safely query shop settings to prevent async MissingGreenlet on un-loaded relation
    settings_q = await db.execute(select(ShopSettings).where(ShopSettings.shop_id == shop.id))
    shop_settings = settings_q.scalar_one_or_none()
    payout_bank = shop_settings.bank_account_last4 if shop_settings else None
    now = datetime.now(timezone.utc)

    if start_date and end_date and isinstance(start_date, str) and isinstance(end_date, str) and start_date != "None" and end_date != "None":
        try:
            since = datetime.strptime(start_date.strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
            until = datetime.strptime(end_date.strip(), "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
        except ValueError:
            since = now - timedelta(days=days)
            until = now
    else:
        since = now - timedelta(days=days)
        until = now

    cutoff_7d = now - timedelta(days=7)

    # -------------------------------------------------------------
    # 1. ORDER ONLINE PAYMENTS
    # -------------------------------------------------------------
    razorpay_actual_payment = and_(
        func.lower(Order.payment_status).in_(["paid", "settled"]),
        func.lower(Order.payment_method) == "online",
        or_(
            and_(
                Order.payment_session_id.is_not(None),
                Order.payment_session_id.startswith("pay_"),
                ~Order.payment_session_id.startswith("pay_mock_")
            ),
            and_(
                Order.razorpay_order_id.is_not(None),
                Order.razorpay_order_id.startswith("order_"),
                ~Order.razorpay_order_id.startswith("order_mock_")
            ),
            and_(
                Order.razorpay_transfer_id.is_not(None),
                Order.razorpay_transfer_id != "",
                ~Order.razorpay_transfer_id.startswith("trf_mock_")
            )
        )
    )

    order_base_conditions = [
        Order.shop_id == shop.id,
        Order.created_at >= since,
        Order.created_at <= until,
        func.lower(Order.order_status).notin_(["rejected", "cancelled", "void"]),
        razorpay_actual_payment
    ]

    if search and search.strip():
        term = f"%{search.strip()}%"
        order_base_conditions.append(
            or_(
                Order.customer_name.ilike(term),
                Order.customer_phone.ilike(term),
                cast(Order.id, String).ilike(term),
                Order.cashfree_order_id.ilike(term),
                Order.payment_session_id.ilike(term),
                Order.razorpay_order_id.ilike(term)
            )
        )

    order_settled_condition = or_(
        Order.settlement_status == "settled",
        and_(Order.settlement_status.is_(None), Order.created_at <= cutoff_7d)
    )
    order_pending_condition = or_(
        Order.settlement_status == "pending",
        and_(Order.settlement_status.is_(None), Order.created_at > cutoff_7d)
    )

    if status_filter == "settled":
        order_base_conditions.append(order_settled_condition)
    elif status_filter == "pending":
        order_base_conditions.append(order_pending_condition)

    # -------------------------------------------------------------
    # 2. SCHEME ONLINE INSTALLMENT PAYMENTS
    # -------------------------------------------------------------
    scheme_online_payment = and_(
        func.lower(SchemePayment.status) == "paid",
        or_(
            func.lower(SchemePayment.payment_method).in_(["online", "razorpay"]),
            and_(
                SchemePayment.transaction_id.is_not(None),
                SchemePayment.transaction_id.startswith("pay_")
            ),
            and_(
                SchemePayment.notes.is_not(None),
                SchemePayment.notes.ilike("%razorpay%")
            )
        )
    )

    scheme_base_conditions = [
        SchemePayment.shop_id == shop.id,
        SchemePayment.paid_at >= since,
        SchemePayment.paid_at <= until,
        scheme_online_payment
    ]

    if search and search.strip():
        term = f"%{search.strip()}%"
        scheme_base_conditions.append(
            or_(
                SchemeMember.customer_name.ilike(term),
                SchemeMember.customer_phone.ilike(term),
                cast(SchemePayment.id, String).ilike(term),
                SchemePayment.transaction_id.ilike(term),
                SchemePayment.notes.ilike(term),
                Scheme.title.ilike(term)
            )
        )

    scheme_settled_condition = or_(
        SchemePayment.settlement_status == "settled",
        and_(SchemePayment.settlement_status.is_(None), SchemePayment.paid_at <= cutoff_7d)
    )
    scheme_pending_condition = or_(
        SchemePayment.settlement_status == "pending",
        and_(SchemePayment.settlement_status.is_(None), SchemePayment.paid_at > cutoff_7d)
    )

    if status_filter == "settled":
        scheme_base_conditions.append(scheme_settled_condition)
    elif status_filter == "pending":
        scheme_base_conditions.append(scheme_pending_condition)

    # -------------------------------------------------------------
    # 3. AGGREGATE TOTALS & COUNTS
    # -------------------------------------------------------------
    # Order Totals
    order_total_count_q = await db.execute(select(func.count(Order.id)).where(*order_base_conditions))
    order_transactions_count = order_total_count_q.scalar() or 0

    order_total_gross_q = await db.execute(select(func.coalesce(func.sum(Order.total_amount), 0.0)).where(*order_base_conditions))
    order_online_sales = float(order_total_gross_q.scalar() or 0.0)

    order_settled_q = await db.execute(
        select(func.count(Order.id), func.coalesce(func.sum(Order.total_amount), 0.0))
        .where(*order_base_conditions, order_settled_condition)
    )
    order_settled_res = order_settled_q.first()
    order_settled_count = order_settled_res[0] or 0
    order_settled_gross = float(order_settled_res[1] or 0.0)

    order_pending_q = await db.execute(
        select(func.count(Order.id), func.coalesce(func.sum(Order.total_amount), 0.0))
        .where(*order_base_conditions, order_pending_condition)
    )
    order_pending_res = order_pending_q.first()
    order_pending_count = order_pending_res[0] or 0
    order_pending_gross = float(order_pending_res[1] or 0.0)

    # Scheme Payments Totals
    scheme_total_count_q = await db.execute(
        select(func.count(SchemePayment.id))
        .join(SchemeMember, SchemePayment.member_id == SchemeMember.id)
        .join(Scheme, SchemePayment.scheme_id == Scheme.id)
        .where(*scheme_base_conditions)
    )
    scheme_transactions_count = scheme_total_count_q.scalar() or 0

    scheme_total_gross_q = await db.execute(
        select(func.coalesce(func.sum(SchemePayment.amount), 0.0))
        .join(SchemeMember, SchemePayment.member_id == SchemeMember.id)
        .join(Scheme, SchemePayment.scheme_id == Scheme.id)
        .where(*scheme_base_conditions)
    )
    scheme_online_sales = float(scheme_total_gross_q.scalar() or 0.0)

    scheme_settled_q = await db.execute(
        select(func.count(SchemePayment.id), func.coalesce(func.sum(SchemePayment.amount), 0.0))
        .join(SchemeMember, SchemePayment.member_id == SchemeMember.id)
        .join(Scheme, SchemePayment.scheme_id == Scheme.id)
        .where(*scheme_base_conditions, scheme_settled_condition)
    )
    scheme_settled_res = scheme_settled_q.first()
    scheme_settled_count = scheme_settled_res[0] or 0
    scheme_settled_gross = float(scheme_settled_res[1] or 0.0)

    scheme_pending_q = await db.execute(
        select(func.count(SchemePayment.id), func.coalesce(func.sum(SchemePayment.amount), 0.0))
        .join(SchemeMember, SchemePayment.member_id == SchemeMember.id)
        .join(Scheme, SchemePayment.scheme_id == Scheme.id)
        .where(*scheme_base_conditions, scheme_pending_condition)
    )
    scheme_pending_res = scheme_pending_q.first()
    scheme_pending_count = scheme_pending_res[0] or 0
    scheme_pending_gross = float(scheme_pending_res[1] or 0.0)

    # Combined Totals
    total_transactions_count = order_transactions_count + scheme_transactions_count
    total_online_sales = round(order_online_sales + scheme_online_sales, 2)
    total_settled_amount = round(order_settled_gross + scheme_settled_gross, 2)
    total_pending_settlement = round(order_pending_gross + scheme_pending_gross, 2)
    settled_count = order_settled_count + scheme_settled_count
    pending_count = order_pending_count + scheme_pending_count

    # -------------------------------------------------------------
    # 4. PAGINATED TRANSACTIONS RETRIEVAL
    # -------------------------------------------------------------
    fetch_window = skip + limit

    orders_q = await db.execute(
        select(Order)
        .where(*order_base_conditions)
        .order_by(desc(Order.created_at))
        .limit(fetch_window)
    )
    paginated_orders = list(orders_q.scalars().all())

    scheme_q = await db.execute(
        select(SchemePayment, SchemeMember, Scheme)
        .join(SchemeMember, SchemePayment.member_id == SchemeMember.id)
        .join(Scheme, SchemePayment.scheme_id == Scheme.id)
        .where(*scheme_base_conditions)
        .order_by(desc(SchemePayment.paid_at))
        .limit(fetch_window)
    )
    paginated_schemes = scheme_q.all()

    combined_items: List[SettlementItemSchema] = []

    # Format Orders
    for o in paginated_orders:
        gross = float(o.total_amount or 0.0)
        net = round(gross, 2)

        created_dt = o.created_at if o.created_at.tzinfo else o.created_at.replace(tzinfo=timezone.utc)
        est_payout_dt = created_dt + timedelta(days=7)
        
        settlement_status = o.settlement_status or ("settled" if now >= est_payout_dt else "pending")
        inv_no = f"SETTL-{created_dt.strftime('%Y%m%d')}-{str(o.id)[:6].upper()}"
        pay_ref = (
            o.payment_session_id 
            if (o.payment_session_id and o.payment_session_id.startswith("pay_"))
            else (o.razorpay_order_id or o.cashfree_order_id or f"RZP-{str(o.id)[:8].upper()}")
        )
        pm = (o.payment_method or "").lower()

        combined_items.append(SettlementItemSchema(
            order_id=str(o.id),
            invoice_no=inv_no,
            payment_reference=pay_ref,
            payment_method=pm or "online",
            customer_name=o.customer_name or "Customer",
            customer_phone=o.customer_phone or "",
            gross_amount=round(gross, 2),
            platform_fee=0.0,
            net_settlement_amount=net,
            order_status=o.order_status,
            payment_status=o.payment_status,
            settlement_status=settlement_status,
            created_at=created_dt.isoformat(),
            estimated_payout_date=est_payout_dt.isoformat(),
            actual_settled_date=o.settled_at.isoformat() if o.settled_at else (est_payout_dt.isoformat() if settlement_status == "settled" else None)
        ))

    # Format Scheme Payments
    for sp, member, sc in paginated_schemes:
        gross = float(sp.amount or 0.0)
        net = round(gross, 2)

        paid_dt = sp.paid_at if sp.paid_at.tzinfo else sp.paid_at.replace(tzinfo=timezone.utc)
        est_payout_dt = paid_dt + timedelta(days=7)

        settlement_status = sp.settlement_status or ("settled" if now >= est_payout_dt else "pending")
        inv_no = f"SCHEME-{paid_dt.strftime('%Y%m%d')}-{str(sp.id)[:6].upper()}"
        pay_ref = sp.transaction_id or f"RZP-SCH-{str(sp.id)[:8].upper()}"

        combined_items.append(SettlementItemSchema(
            order_id=str(sp.id),
            invoice_no=inv_no,
            payment_reference=pay_ref,
            payment_method="online (Scheme)",
            customer_name=f"{member.customer_name} ({sc.title} #{sp.installment_number})",
            customer_phone=member.customer_phone or "",
            gross_amount=round(gross, 2),
            platform_fee=0.0,
            net_settlement_amount=net,
            order_status="completed",
            payment_status=sp.status or "paid",
            settlement_status=settlement_status,
            created_at=paid_dt.isoformat(),
            estimated_payout_date=est_payout_dt.isoformat(),
            actual_settled_date=sp.settled_at.isoformat() if sp.settled_at else (est_payout_dt.isoformat() if settlement_status == "settled" else None)
        ))

    # Sort all items chronologically by created_at descending
    combined_items.sort(key=lambda item: item.created_at, reverse=True)

    # Slice for current pagination offset
    paginated_settlements = combined_items[skip : skip + limit]

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

    has_more = (skip + len(paginated_settlements)) < total_transactions_count

    return SettlementSummaryResponse(
        total_online_sales=total_online_sales,
        total_settled_amount=total_settled_amount,
        total_pending_settlement=total_pending_settlement,
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
        settlements=paginated_settlements
    )
