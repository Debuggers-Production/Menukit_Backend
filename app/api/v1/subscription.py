import hmac
import hashlib
import uuid
import json
import math
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

import logging
from app.database.session import get_db
from app.models.shop import Shop
from app.models.subscription import Subscription, PaymentTransaction
from app.core.config import get_settings
from app.core.deps import get_current_user, get_current_shop_context, require_permission
from app.models.user import User
from app.services.pricing_engine import pricing_engine, MODULE_METADATA, COUNTRIES_CONFIG, BASE_INR_PRICES
from app.services.geo_service import geo_service

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()

# Initialize Razorpay Client
razorpay_client = None
if settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET:
    try:
        import razorpay
        razorpay_client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    except ImportError:
        print("Warning: razorpay package not installed or initialized.")
        razorpay_client = None


class CreateOrderRequest(BaseModel):
    is_all_access: bool
    selected_modules: List[str]
    billing_cycle: Optional[str] = "monthly"
    country_code: Optional[str] = None
    is_autopay: Optional[bool] = True


class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: Optional[str] = None
    razorpay_subscription_id: Optional[str] = None
    razorpay_payment_id: str
    razorpay_signature: str


@router.get("/pricing")
async def get_public_pricing(
    request: Request,
    country: Optional[str] = None,
    billing_cycle: Optional[str] = "monthly"
):
    """
    Get dynamic, country-specific pricing catalog for all plans and modules.
    Master India (INR) price is automatically converted using real-time FX and rounded.
    """
    country_code = country
    if not country_code or country_code.strip() == "":
        country_code = await geo_service.detect_country_code(request)
    return await pricing_engine.get_pricing_catalog(country_code, billing_cycle or "monthly")


@router.get("/detect-country")
async def detect_visitor_country(request: Request):
    """Detect visitor's country based on IP geolocation and proxy headers."""
    country_cfg = await geo_service.get_detected_country_config(request)
    return {
        "code": country_cfg.code,
        "name": country_cfg.name,
        "currency": country_cfg.currency,
        "symbol": country_cfg.symbol,
        "flag": country_cfg.flag,
    }


@router.post("/create-order")
async def create_order(
    request: CreateOrderRequest,
    raw_request: Request,
    shop: Shop = Depends(require_permission("settings", "write")),
    db: AsyncSession = Depends(get_db)
):
    """
    Creates a Razorpay / Gateway order using backend single-source-of-truth pricing engine.
    Validates country, calculates FX rate, rounds to clean price, and secures payment values.
    """
    country_code = request.country_code
    if not country_code or country_code.strip() == "":
        country_code = await geo_service.detect_country_code(raw_request)

    logger.info(f"Create order payload: is_all_access={request.is_all_access}, modules={request.selected_modules}, country={country_code}, cycle={request.billing_cycle}")

    # Securely calculate order total on backend
    calc = await pricing_engine.calculate_order_total(
        is_all_access=request.is_all_access,
        selected_modules=request.selected_modules,
        country_code=country_code,
        billing_cycle=request.billing_cycle or "monthly"
    )

    logger.info(f"Calculated order total: {calc}")

    if calc["base_subtotal"] <= 0:
        raise HTTPException(status_code=400, detail="Total amount cannot be zero. Please select the All-Access pack or at least one module.")

    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    final_total = calc["final_total"]
    currency = calc["currency"]
    amount_subunits = calc["amount_subunits"]
    fx_rate = calc["fx_rate"]

    is_autopay = True if request.is_autopay is None else bool(request.is_autopay)

    # 1. Mock / Fallback Mode
    if settings.MOCK_PAYMENT_MODE:
        mock_order_id = f"order_mock_{uuid.uuid4().hex[:14]}"
        
        transaction = PaymentTransaction(
            shop_id=shop.id,
            razorpay_order_id=mock_order_id,
            amount=final_total,
            currency=currency,
            country_code=calc["country_code"],
            fx_rate=fx_rate,
            status="created",
            is_all_access=request.is_all_access,
            purchased_modules=request.selected_modules,
            billing_cycle=request.billing_cycle or "monthly",
            is_autopay=is_autopay
        )
        db.add(transaction)
        await db.commit()
        
        return {
            "order_id": mock_order_id,
            "base_amount": calc["base_subtotal"],
            "pg_fee": calc["pg_fee"],
            "gst_on_fee": calc["gst_on_fee"],
            "final_total": final_total,
            "amount": amount_subunits,
            "currency": currency,
            "currency_symbol": calc["currency_symbol"],
            "mock_mode": True,
            "is_autopay": is_autopay,
            "billing_cycle": request.billing_cycle or "monthly",
            "key": settings.RAZORPAY_KEY_ID or "rzp_test_mock"
        }

    # 2. Real Razorpay Mode
    try:
        # A. AUTOPAY / RECURRING MANDATE (Razorpay Subscriptions)
        if is_autopay:
            try:
                cycle = request.billing_cycle or "monthly"
                period = "yearly" if cycle == "yearly" else "monthly"
                plan_name = f"Menukit {'All-Access' if request.is_all_access else 'Modular'} ({cycle.title()})"

                sub_amount = amount_subunits
                sub_curr = currency
                if sub_curr != "INR":
                    sub_amount = int(round(calc["inr_equivalent"] * 100))
                    sub_curr = "INR"

                plan_payload = {
                    "period": period,
                    "interval": 1,
                    "item": {
                        "name": plan_name,
                        "amount": sub_amount,
                        "currency": sub_curr,
                        "description": f"Menukit Subscription - {cycle.title()} Auto-Pay"
                    }
                }
                plan = razorpay_client.plan.create(data=plan_payload)

                sub_payload = {
                    "plan_id": plan["id"],
                    "total_count": 60 if cycle == "monthly" else 10,
                    "quantity": 1,
                    "customer_notify": 1,
                    "notes": {
                        "shop_id": str(shop.id),
                        "is_all_access": "true" if request.is_all_access else "false",
                        "billing_cycle": cycle,
                        "is_autopay": "true",
                        "country_code": calc["country_code"],
                        "currency": currency,
                        "base_amount": str(calc["base_subtotal"]),
                        "pg_fee": str(calc["pg_fee"]),
                        "gst_on_fee": str(calc["gst_on_fee"]),
                        "fx_rate": str(fx_rate)
                    }
                }
                sub_res = razorpay_client.subscription.create(data=sub_payload)
                sub_id = sub_res["id"]

                transaction = PaymentTransaction(
                    shop_id=shop.id,
                    razorpay_order_id=sub_id,
                    amount=final_total,
                    currency=currency,
                    country_code=calc["country_code"],
                    fx_rate=fx_rate,
                    status="created",
                    is_all_access=request.is_all_access,
                    purchased_modules=request.selected_modules,
                    billing_cycle=cycle,
                    is_autopay=True
                )
                db.add(transaction)
                await db.commit()

                return {
                    "subscription_id": sub_id,
                    "order_id": sub_id,
                    "base_amount": calc["base_subtotal"],
                    "pg_fee": calc["pg_fee"],
                    "gst_on_fee": calc["gst_on_fee"],
                    "final_total": final_total,
                    "amount": sub_amount,
                    "currency": sub_curr,
                    "currency_symbol": calc["currency_symbol"],
                    "mock_mode": False,
                    "is_autopay": True,
                    "billing_cycle": cycle,
                    "key": settings.RAZORPAY_KEY_ID
                }
            except Exception as rzp_sub_err:
                logger.error(f"Razorpay subscription creation failed: {rzp_sub_err}, falling back to direct order")

        # B. DIRECT ONE-TIME ORDER (When is_autopay is False, or fallback)
        order_data = {
            "amount": amount_subunits,
            "currency": currency,
            "receipt": f"sub_rcpt_{shop.id.hex[:10]}_{int(datetime.now().timestamp())}",
            "notes": {
                "shop_id": str(shop.id),
                "is_all_access": "true" if request.is_all_access else "false",
                "billing_cycle": request.billing_cycle or "monthly",
                "is_autopay": "false",
                "country_code": calc["country_code"],
                "currency": currency,
                "base_amount": str(calc["base_subtotal"]),
                "pg_fee": str(calc["pg_fee"]),
                "gst_on_fee": str(calc["gst_on_fee"]),
                "fx_rate": str(fx_rate)
            }
        }
        
        try:
            order = razorpay_client.order.create(data=order_data)
        except Exception as rzp_err:
            # If foreign currency is not supported by merchant account settings, seamlessly convert to INR
            if currency != "INR":
                inr_paise = int(round(calc["inr_equivalent"] * 100))
                order_data["amount"] = inr_paise
                order_data["currency"] = "INR"
                order = razorpay_client.order.create(data=order_data)
            else:
                raise rzp_err
        
        # Save pending transaction
        transaction = PaymentTransaction(
            shop_id=shop.id,
            razorpay_order_id=order['id'],
            amount=final_total,
            currency=currency,
            country_code=calc["country_code"],
            fx_rate=fx_rate,
            status="created",
            is_all_access=request.is_all_access,
            purchased_modules=request.selected_modules,
            billing_cycle=request.billing_cycle or "monthly",
            is_autopay=is_autopay
        )
        db.add(transaction)
        await db.commit()
        
        return {
            "subscription_id": None,
            "order_id": order['id'],
            "base_amount": calc["base_subtotal"],
            "pg_fee": calc["pg_fee"],
            "gst_on_fee": calc["gst_on_fee"],
            "final_total": final_total,
            "amount": order['amount'],
            "currency": order['currency'],
            "currency_symbol": calc["currency_symbol"],
            "mock_mode": False,
            "is_autopay": is_autopay,
            "billing_cycle": request.billing_cycle or "monthly",
            "key": settings.RAZORPAY_KEY_ID
        }
    except Exception as e:
        logger.error(f"Razorpay order creation error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create Razorpay payment: {str(e)}")


@router.post("/verify")
async def verify_payment(
    request: VerifyPaymentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Verifies Razorpay payment signature and activates the subscription."""
    search_id = request.razorpay_subscription_id or request.razorpay_order_id
    if not search_id:
        raise HTTPException(status_code=400, detail="Missing razorpay_order_id or razorpay_subscription_id")

    stmt = select(PaymentTransaction).where(
        (PaymentTransaction.razorpay_order_id == search_id) |
        (PaymentTransaction.razorpay_payment_id == request.razorpay_payment_id)
    )
    result = await db.execute(stmt)
    transaction = result.scalar_one_or_none()
    
    if not transaction:
        raise HTTPException(status_code=404, detail="Order or subscription transaction not found")
        
    if transaction.status == "success":
        return {"status": "already_verified", "message": "Subscription active"}

    is_valid = False
    
    if settings.MOCK_PAYMENT_MODE and search_id.startswith("order_mock_"):
        # Accept mock payments
        is_valid = True
    else:
        if not razorpay_client:
            raise HTTPException(status_code=500, detail="Razorpay client is not configured")
            
        try:
            if request.razorpay_subscription_id:
                # Razorpay Subscriptions / AutoPay Signature Verification
                params_dict = {
                    'razorpay_subscription_id': request.razorpay_subscription_id,
                    'razorpay_payment_id': request.razorpay_payment_id,
                    'razorpay_signature': request.razorpay_signature
                }
                razorpay_client.utility.verify_subscription_payment_signature(params_dict)
                is_valid = True
            else:
                # Razorpay Standard Order Signature Verification
                params_dict = {
                    'razorpay_order_id': request.razorpay_order_id,
                    'razorpay_payment_id': request.razorpay_payment_id,
                    'razorpay_signature': request.razorpay_signature
                }
                razorpay_client.utility.verify_payment_signature(params_dict)
                is_valid = True
        except Exception as e:
            logger.error(f"Razorpay signature verification failed: {e}")
            is_valid = False

    if not is_valid:
        transaction.status = "failed"
        await db.commit()
        raise HTTPException(status_code=400, detail="Invalid payment signature")

    # Payment Successful!
    transaction.status = "success"
    transaction.razorpay_payment_id = request.razorpay_payment_id
    transaction.razorpay_signature = request.razorpay_signature
    
    # Generate Invoice Number
    from app.services.invoice_service import InvoiceService
    from app.services.email_service import EmailService
    
    inv_number = InvoiceService.generate_invoice_number(str(transaction.id))
    transaction.invoice_number = inv_number

    # Update or Create Subscription
    stmt = select(Subscription).where(Subscription.shop_id == transaction.shop_id)
    result = await db.execute(stmt)
    subscription = result.scalar_one_or_none()
    
    if not subscription:
        subscription = Subscription(shop_id=transaction.shop_id)
        db.add(subscription)
        
    now = datetime.now(timezone.utc)
    duration_days = 365 if getattr(transaction, "billing_cycle", "monthly") == "yearly" else 30
    
    # 1. Gather current expirations for ALL modules
    raw_expirations = dict(getattr(subscription, "module_expirations", {}) or {})
    module_expirations = {}
    for k, v in raw_expirations.items():
        if isinstance(v, str):
            try:
                dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                module_expirations[k] = dt
            except Exception:
                pass
        elif isinstance(v, datetime):
            dt = v
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            module_expirations[k] = dt

    existing_period_end = subscription.current_period_end
    if existing_period_end and existing_period_end.tzinfo is None:
        existing_period_end = existing_period_end.replace(tzinfo=timezone.utc)

    # 2. Ensure all previously active modules have a baseline expiration
    all_current_active = ALL_MARKETPLACE_MODULES if getattr(subscription, "is_all_access", False) else list(subscription.active_modules or [])
    
    for mod in all_current_active:
        if mod not in module_expirations:
            if existing_period_end:
                module_expirations[mod] = existing_period_end
            else:
                module_expirations[mod] = now

    # 3. Update expirations for purchased modules
    modules_to_update = ALL_MARKETPLACE_MODULES if transaction.is_all_access else (transaction.purchased_modules or [])
    
    for mod in modules_to_update:
        prev_exp = module_expirations.get(mod)
        if prev_exp and prev_exp > now:
            # Add to existing remaining days
            module_expirations[mod] = prev_exp + timedelta(days=duration_days)
        else:
            # Start fresh from today
            module_expirations[mod] = now + timedelta(days=duration_days)

    # Normalize and sync legacy alias keys so they never diverge or report as expired
    if "member-count" in module_expirations or "member-details" in module_expirations:
        module_expirations["new-member"] = module_expirations.get("member-count") or module_expirations.get("member-details")
    if "analytics-advanced" in module_expirations:
        module_expirations["analytics-advanced-filters"] = module_expirations["analytics-advanced"]
        module_expirations["analytics-customer-insights"] = module_expirations["analytics-advanced"]

    # 4. Rebuild active_modules based on expiration > now
    active_modules = []
    for mod, exp in module_expirations.items():
        if exp > now:
            active_modules.append(mod)
            
    # Remove duplicates
    active_modules = list(dict.fromkeys(active_modules))
    
    subscription.active_modules = active_modules
    subscription.is_active = len(active_modules) > 0
    
    if transaction.is_all_access:
        # If they explicitly bought all-access in this transaction
        subscription.is_all_access = True
    else:
        # If they bought individual modules, their current subscription plan is no longer All-Access
        subscription.is_all_access = False

    subscription.is_trial = False
    subscription.auto_renew = getattr(transaction, "is_autopay", True) if getattr(transaction, "is_autopay", None) is not None else True
    subscription.billing_cycle = getattr(transaction, "billing_cycle", "monthly") or "monthly"

    # Cancel previous Razorpay subscription mandate if switching cycle or plan
    if subscription.razorpay_subscription_id and request.razorpay_subscription_id and subscription.razorpay_subscription_id != request.razorpay_subscription_id and razorpay_client:
        try:
            razorpay_client.subscription.cancel(subscription.razorpay_subscription_id)
            logger.info(f"Cancelled previous Razorpay subscription {subscription.razorpay_subscription_id} after cycle switch to {transaction.billing_cycle}")
        except Exception as old_sub_err:
            logger.warning(f"Could not cancel previous Razorpay subscription {subscription.razorpay_subscription_id}: {old_sub_err}")

    if request.razorpay_subscription_id:
        subscription.razorpay_subscription_id = request.razorpay_subscription_id

    # Save serialized ISO strings
    subscription.module_expirations = {
        k: v.isoformat() for k, v in module_expirations.items()
    }
    
    # Global subscription end is max among all active module expiration dates
    if module_expirations:
        subscription.current_period_end = max(module_expirations.values())

    # Sync subscription across all shops owned by the user
    other_shops = []
    is_paid_discovery = transaction.is_all_access or "hide-discovery-badge" in (transaction.purchased_modules or [])
    try:
        from app.models.shop_settings import ShopSettings
        shop_stmt = select(Shop).where(Shop.id == transaction.shop_id)
        shop_res = await db.execute(shop_stmt)
        curr_shop = shop_res.scalar_one_or_none()

        if curr_shop and is_paid_discovery:
            if not curr_shop.settings:
                curr_shop.settings = ShopSettings(shop_id=curr_shop.id)
                db.add(curr_shop.settings)
                await db.flush()
            curr_shop.settings.is_discoverable = True
            curr_shop.settings.hide_discovery_badge = True

        if curr_shop and curr_shop.user_id:
            all_user_shops_res = await db.execute(
                select(Shop).where(Shop.user_id == curr_shop.user_id, Shop.id != curr_shop.id)
            )
            other_shops = all_user_shops_res.scalars().all()
            for o_shop in other_shops:
                o_sub_stmt = select(Subscription).where(Subscription.shop_id == o_shop.id)
                o_sub_res = await db.execute(o_sub_stmt)
                o_sub = o_sub_res.scalar_one_or_none()
                if not o_sub:
                    o_sub = Subscription(shop_id=o_shop.id)
                    db.add(o_sub)
                o_sub.active_modules = subscription.active_modules
                o_sub.is_active = subscription.is_active
                o_sub.is_all_access = subscription.is_all_access
                o_sub.is_trial = subscription.is_trial
                o_sub.auto_renew = subscription.auto_renew
                o_sub.billing_cycle = subscription.billing_cycle
                o_sub.razorpay_subscription_id = subscription.razorpay_subscription_id
                o_sub.module_expirations = subscription.module_expirations
                o_sub.current_period_end = subscription.current_period_end

                if is_paid_discovery and o_shop:
                    if not o_shop.settings:
                        o_shop.settings = ShopSettings(shop_id=o_shop.id)
                        db.add(o_shop.settings)
                        await db.flush()
                    o_shop.settings.is_discoverable = True
                    o_shop.settings.hide_discovery_badge = True
    except Exception as sync_err:
        logger.warning(f"Failed to sync subscription across shops: {sync_err}")

    await db.commit()

    if is_paid_discovery:
        try:
            from app.database.redis import invalidate_shop_cache
            if curr_shop:
                await invalidate_shop_cache(str(curr_shop.id), slug=curr_shop.slug)
            for o_shop in other_shops:
                await invalidate_shop_cache(str(o_shop.id), slug=o_shop.slug)
        except Exception as cache_err:
            logger.warning(f"Failed to invalidate cache after paid discovery activation: {cache_err}")
    
    # Send Invoice Email
    try:
        stmt = select(Shop).where(Shop.id == transaction.shop_id)
        shop_res = await db.execute(stmt)
        shop_obj = shop_res.scalar_one_or_none()
        shop_name = shop_obj.name if shop_obj else "SmartMenu Store"

        invoice_data = InvoiceService.build_invoice_data(
            transaction=transaction,
            user_email=current_user.email,
            shop_name=shop_name,
            invoice_number=inv_number
        )
        email_svc = EmailService()
        await email_svc.send_subscription_invoice_email(current_user.email, invoice_data)
    except Exception as e:
        print(f"Failed to dispatch invoice email: {e}")

    return {
        "status": "success",
        "message": "Subscription activated successfully",
        "invoice_number": inv_number,
        "transaction_id": str(transaction.id)
    }


ALL_MARKETPLACE_MODULES = [
    "online-orders", "member-count", "member-details", 
    "search-data", "custom-theme", "analytics-advanced", "hide-discovery-badge"
]

MODULE_ALIASES = {
    "new-member": "member-count",
    "analytics-advanced-filters": "analytics-advanced",
    "analytics-customer-insights": "analytics-advanced",
}


async def get_shop_subscription_status(shop: Shop, db: AsyncSession) -> dict:
    """Helper to compute shop subscription status including trial, grace period, and mock overrides."""
    stmt = select(Subscription).where(Subscription.shop_id == shop.id)
    result = await db.execute(stmt)
    subscription = result.scalar_one_or_none()
    
    now = datetime.now(timezone.utc)
    
    # 1. If shop has no subscription yet, check if user's primary shop has one to inherit!
    if not subscription:
        # Check if user has a primary shop with active subscription
        primary_sub = None
        if shop.user_id:
            user_sub_stmt = (
                select(Subscription)
                .join(Shop, Subscription.shop_id == Shop.id)
                .where(Shop.user_id == shop.user_id, Shop.id != shop.id)
                .order_by(Shop.created_at.asc())
            )
            user_sub_res = await db.execute(user_sub_stmt)
            primary_sub = user_sub_res.scalars().first()

        if primary_sub:
            subscription = Subscription(
                shop_id=shop.id,
                is_active=primary_sub.is_active,
                is_all_access=primary_sub.is_all_access,
                is_trial=primary_sub.is_trial,
                active_modules=primary_sub.active_modules,
                module_expirations=primary_sub.module_expirations,
                current_period_end=primary_sub.current_period_end
            )
        else:
            created_at = shop.created_at or now
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            trial_end = created_at + timedelta(days=settings.FREE_TRIAL_DAYS)
            
            initial_expirations = {
                mod: trial_end.isoformat() for mod in ALL_MARKETPLACE_MODULES
            }
            
            subscription = Subscription(
                shop_id=shop.id,
                is_active=True,
                is_all_access=True,
                is_trial=True,
                active_modules=ALL_MARKETPLACE_MODULES,
                module_expirations=initial_expirations,
                current_period_end=trial_end
            )
        db.add(subscription)
        await db.commit()
        await db.refresh(subscription)

    # 2. Extract and parse module expirations
    raw_exp = dict(getattr(subscription, "module_expirations", {}) or {})
    parsed_expirations: Dict[str, datetime] = {}
    tracked_dts = []
    
    for k, v in raw_exp.items():
        if isinstance(v, str):
            try:
                dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                parsed_expirations[k] = dt
                tracked_dts.append(dt)
            except Exception:
                pass
        elif isinstance(v, datetime):
            dt = v
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            parsed_expirations[k] = dt
            tracked_dts.append(dt)

    # Reconcile alias and parent-child expirations
    # If member-details or member-count is active, reconcile new-member
    max_member_exp = max(
        [dt for k, dt in parsed_expirations.items() if k in ("member-details", "member-count", "new-member")],
        default=None
    )
    if max_member_exp:
        parsed_expirations["member-count"] = max(parsed_expirations.get("member-count", max_member_exp), max_member_exp)
        parsed_expirations["new-member"] = max_member_exp

    # If analytics-advanced is active, reconcile sub-keys
    max_ana_exp = max(
        [dt for k, dt in parsed_expirations.items() if k in ("analytics-advanced", "analytics-advanced-filters", "analytics-customer-insights")],
        default=None
    )
    if max_ana_exp:
        parsed_expirations["analytics-advanced"] = max(parsed_expirations.get("analytics-advanced", max_ana_exp), max_ana_exp)
        parsed_expirations["analytics-advanced-filters"] = max_ana_exp
        parsed_expirations["analytics-customer-insights"] = max_ana_exp

    # 3. Determine overall period_end
    # If module expirations exist, the subscription period end is determined by module expirations
    if tracked_dts:
        period_end = max(tracked_dts)
    else:
        period_end = subscription.current_period_end
        if period_end and period_end.tzinfo is None:
            period_end = period_end.replace(tzinfo=timezone.utc)

    if not period_end:
        created_at = subscription.created_at or now
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        period_end = created_at + timedelta(days=settings.FREE_TRIAL_DAYS)

    grace_period_days = 0
    is_trial = getattr(subscription, "is_trial", False)
    is_grace_period = False
    grace_days_left = 0

    if now <= period_end:
        is_active = True
        is_expired = False
        days_left = max(0, int(math.ceil((period_end - now).total_seconds() / 86400)))
        status_msg = f"Free Trial active ({days_left} day{'s' if days_left != 1 else ''} left)" if is_trial else f"Active subscription ({days_left} day{'s' if days_left != 1 else ''} left)"
    else:
        # Strictly expired immediately when period ends - zero grace period
        is_active = False
        is_expired = True
        days_left = 0
        status_msg = "Free Trial ended. Features locked. Please renew to continue." if is_trial else "Subscription ended. Features locked. Please renew to continue."

    # Environment Mock Override for UI Banner Testing
    mock_state = (getattr(settings, "MOCK_SUBSCRIPTION_STATE", "none") or "none").lower()
    if mock_state == "ending_soon":
        is_active = True
        is_expired = False
        days_left = 2
        status_msg = "Mock: Free Trial / Subscription Ending Soon (2 days left)"
    elif mock_state == "expired":
        is_active = False
        is_expired = True
        days_left = 0
        status_msg = "Mock: Subscription Ended. Features Locked."

    # 4. Format per-module expiration details and dynamic active modules
    fallback_dt = period_end
    dynamic_active_modules = []
    formatted_module_expirations = {}

    # Only evaluate legitimate marketplace modules (filter out internal sub-keys and legacy aliases)
    all_eval_mods = ALL_MARKETPLACE_MODULES

    for mod in all_eval_mods:
        mod_exp_dt = parsed_expirations.get(mod)
        if not mod_exp_dt:
            # If All-Access or Trial, inherit global period_end
            if getattr(subscription, "is_all_access", False) or getattr(subscription, "is_trial", False):
                mod_exp_dt = period_end
            else:
                mod_exp_dt = fallback_dt if (subscription.active_modules and mod in subscription.active_modules) else None

        if mod_exp_dt and now <= mod_exp_dt:
            mod_days_left = max(0, int(math.ceil((mod_exp_dt - now).total_seconds() / 86400)))
            is_mod_active = True
        else:
            mod_days_left = 0
            is_mod_active = False

        if is_mod_active and is_active:
            dynamic_active_modules.append(mod)

        formatted_module_expirations[mod] = {
            "expires_at": mod_exp_dt.isoformat() if mod_exp_dt else None,
            "days_left": mod_days_left
        }

    # If all modules expired, ensure global is_active is False
    if not dynamic_active_modules:
        is_active = False
        is_expired = True
        status_msg = "Free Trial ended. Features locked. Please renew to continue." if is_trial else "Subscription ended. Features locked. Please renew to continue."

    # Check actual All-Access
    if is_expired:
        is_actual_all_access = False
    elif is_trial:
        all_mods_active = all(
            formatted_module_expirations.get(m, {}).get("days_left", 0) > 0
            for m in ALL_MARKETPLACE_MODULES
        )
        is_actual_all_access = is_active and all_mods_active
    else:
        # Check if all legitimate modules are active
        all_canonical_active = all(
            formatted_module_expirations.get(m, {}).get("days_left", 0) > 0
            for m in ALL_MARKETPLACE_MODULES
        )
        if all_canonical_active and is_active:
            is_actual_all_access = True
        else:
            is_actual_all_access = False
            if getattr(subscription, "is_all_access", False) and is_active:
                stmt_aa = select(PaymentTransaction).where(
                    PaymentTransaction.shop_id == shop.id,
                    PaymentTransaction.status == "success"
                ).order_by(PaymentTransaction.created_at.desc())
                aa_res = await db.execute(stmt_aa)
                latest_tx = aa_res.scalars().first()
                is_actual_all_access = latest_tx.is_all_access if latest_tx else True

    # Check for expired modules (0 days left) among marketplace modules
    # A module is only expired if the shop was subscribed to it or has a modular plan where some features expired
    expired_mods = [
        mod for mod in ALL_MARKETPLACE_MODULES
        if formatted_module_expirations.get(mod, {}).get("days_left", 0) == 0
        and (
            getattr(subscription, "is_all_access", False)
            or getattr(subscription, "is_trial", False)
            or (subscription.active_modules and mod in subscription.active_modules)
        )
    ]
    # Only report has_expired_modules if there are actual expired modules AND not all modules are active
    has_expired_modules = len(expired_mods) > 0 and len(dynamic_active_modules) < len(ALL_MARKETPLACE_MODULES)

    # Active days list (only modules that actually have > 0 days left)
    active_days_list = [
        info["days_left"] for mod, info in formatted_module_expirations.items()
        if info.get("days_left", 0) > 0 and mod in ALL_MARKETPLACE_MODULES
    ]

    # If any module is genuinely expired, the least days left is 0!
    if has_expired_modules:
        core_days_left = 0
        effective_days_left = 0
        is_actual_all_access = False
        if not is_expired:
            status_msg = f"{len(expired_mods)} add-on feature(s) expired (0 days left). Features locked. Please renew to continue."
    elif active_days_list:
        core_days_left = min(active_days_list)
        effective_days_left = core_days_left
        status_msg = f"Active subscription ({core_days_left} day{'s' if core_days_left != 1 else ''} left)"
    else:
        core_days_left = days_left
        effective_days_left = days_left

    # Sync back to subscription model if needed
    if (subscription.is_active != is_active or 
        subscription.is_all_access != is_actual_all_access or
        subscription.current_period_end != period_end or 
        subscription.active_modules != dynamic_active_modules or
        has_expired_modules != (len(expired_mods) > 0)) and mock_state == "none":
        subscription.is_active = is_active
        subscription.is_all_access = is_actual_all_access
        subscription.current_period_end = period_end
        subscription.active_modules = dynamic_active_modules
        
        # Clean up stale legacy keys in database
        synced_exp = {}
        for m in ALL_MARKETPLACE_MODULES:
            if m in formatted_module_expirations and formatted_module_expirations[m].get("expires_at"):
                synced_exp[m] = formatted_module_expirations[m]["expires_at"]
        # Maintain alias entries matching canonical values so existing db constraints stay happy
        synced_exp["new-member"] = synced_exp.get("member-count") or synced_exp.get("member-details")
        synced_exp["analytics-advanced-filters"] = synced_exp.get("analytics-advanced")
        synced_exp["analytics-customer-insights"] = synced_exp.get("analytics-advanced")
        subscription.module_expirations = synced_exp
        await db.commit()

    # Auto-activate Paid Discovery settings (visible on map, hidden menu discover badge)
    # if merchant has an active hide-discovery-badge module or All-Access
    hide_discovery_info = formatted_module_expirations.get("hide-discovery-badge", {})
    hide_discovery_days = hide_discovery_info.get("days_left", 0)
    has_active_paid_discovery = (
        is_active
        and not is_expired
        and (is_actual_all_access or "hide-discovery-badge" in dynamic_active_modules)
        and hide_discovery_days > 0
    )

    if has_active_paid_discovery and shop:
        try:
            from app.models.shop_settings import ShopSettings
            from app.database.redis import invalidate_shop_cache

            if not shop.settings:
                stmt_s = select(ShopSettings).where(ShopSettings.shop_id == shop.id)
                res_s = await db.execute(stmt_s)
                shop.settings = res_s.scalar_one_or_none()
                if not shop.settings:
                    shop.settings = ShopSettings(shop_id=shop.id)
                    db.add(shop.settings)
                    await db.flush()

            is_disc = getattr(shop.settings, "is_discoverable", None)
            hide_badge = getattr(shop.settings, "hide_discovery_badge", None)

            if is_disc is not True or hide_badge is not True:
                shop.settings.is_discoverable = True
                shop.settings.hide_discovery_badge = True
                await db.commit()
                await db.refresh(shop.settings)
                try:
                    await invalidate_shop_cache(str(shop.id), slug=shop.slug)
                except Exception as cache_err:
                    logger.warning(f"Failed to invalidate cache during discovery auto-activation: {cache_err}")
        except Exception as e:
            logger.warning(f"Error checking/auto-updating discovery settings in get_shop_subscription_status: {e}")

    return {
        "is_active": is_active,
        "is_all_access": is_actual_all_access,
        "active_modules": dynamic_active_modules if is_active else [],
        "module_expirations": formatted_module_expirations,
        "current_period_end": period_end.isoformat() if period_end else None,
        "is_trial": is_trial,
        "is_expired": is_expired,
        "is_grace_period": is_grace_period,
        "grace_days_left": grace_days_left,
        "days_left": effective_days_left,
        "core_days_left": core_days_left,
        "max_days_left": days_left,
        "has_expired_modules": has_expired_modules,
        "expired_modules_count": len(expired_mods),
        "expired_modules": expired_mods,
        "has_expiring_modules": (core_days_left <= 5 and not is_expired and not is_grace_period and not has_expired_modules),
        "free_trial_days": settings.FREE_TRIAL_DAYS,
        "grace_period_days": settings.GRACE_PERIOD_DAYS,
        "status_message": status_msg,
        "auto_renew": bool(
            getattr(subscription, "auto_renew", False)
            and getattr(subscription, "razorpay_subscription_id", None)
            and not is_trial
        ),
        "has_mandate": bool(getattr(subscription, "razorpay_subscription_id", None)),
        "billing_cycle": getattr(subscription, "billing_cycle", "monthly") or "monthly",
    }


class ToggleAutopayRequest(BaseModel):
    auto_renew: bool


@router.post("/toggle-autopay")
async def toggle_autopay(
    payload: ToggleAutopayRequest,
    shop: Shop = Depends(get_current_shop_context),
    db: AsyncSession = Depends(get_db)
):
    """Toggle auto-pay / auto-renew for the shop's subscription."""
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    stmt = select(Subscription).where(Subscription.shop_id == shop.id)
    result = await db.execute(stmt)
    subscription = result.scalar_one_or_none()

    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")

    # Handle Disabling Auto-Pay: Cancel mandate on gateway
    if not payload.auto_renew:
        subscription.auto_renew = False
        if subscription.razorpay_subscription_id and razorpay_client:
            try:
                razorpay_client.subscription.cancel(subscription.razorpay_subscription_id)
                logger.info(f"Cancelled Razorpay subscription mandate {subscription.razorpay_subscription_id} immediately on gateway.")
            except Exception as rzp_cancel_err:
                logger.warning(f"Failed to cancel Razorpay subscription {subscription.razorpay_subscription_id}: {rzp_cancel_err}")
    else:
        # Handle Enabling Auto-Pay: Check if an active mandate exists
        needs_mandate_setup = False
        if subscription.razorpay_subscription_id and razorpay_client:
            try:
                rzp_sub = razorpay_client.subscription.fetch(subscription.razorpay_subscription_id)
                if rzp_sub.get("status") in ["cancelled", "completed"]:
                    needs_mandate_setup = True
            except Exception as check_err:
                logger.warning(f"Error checking razorpay subscription status: {check_err}")
                needs_mandate_setup = True
        else:
            needs_mandate_setup = True

        if needs_mandate_setup:
            return {
                "status": "mandate_required",
                "auto_renew": False,
                "needs_mandate_setup": True,
                "message": "To reactivate Auto-Pay, please authorize your new recurring mandate."
            }

        subscription.auto_renew = True

    # Sync across all shops owned by the user
    try:
        if shop.user_id:
            all_user_shops_res = await db.execute(
                select(Shop).where(Shop.user_id == shop.user_id, Shop.id != shop.id)
            )
            for o_shop in all_user_shops_res.scalars().all():
                o_sub_res = await db.execute(select(Subscription).where(Subscription.shop_id == o_shop.id))
                o_sub = o_sub_res.scalar_one_or_none()
                if o_sub:
                    o_sub.auto_renew = payload.auto_renew
    except Exception as e:
        logger.warning(f"Failed to sync autopay state across shops: {e}")

    await db.commit()

    cycle = getattr(subscription, "billing_cycle", "monthly") or "monthly"
    freq = "every year" if cycle == "yearly" else "every month"

    msg = (
        f"Autopay enabled. Your subscription will automatically renew {freq}."
        if payload.auto_renew
        else "Autopay disabled. Your subscription will remain active until its expiration date and will not automatically renew."
    )

    return {
        "status": "success",
        "auto_renew": subscription.auto_renew,
        "billing_cycle": cycle,
        "message": msg
    }


@router.get("/current")
async def get_current_subscription(
    shop: Shop = Depends(get_current_shop_context),
    db: AsyncSession = Depends(get_db)
):
    """Get active subscription details for the current shop including trial & grace period status."""
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
        
    return await get_shop_subscription_status(shop, db)


@router.get("/history")
async def get_billing_history(
    shop: Shop = Depends(get_current_shop_context),
    db: AsyncSession = Depends(get_db)
):
    """Get all past subscription transactions and invoices."""
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    stmt = select(PaymentTransaction).where(
        PaymentTransaction.shop_id == shop.id,
        PaymentTransaction.status == "success"
    ).order_by(PaymentTransaction.created_at.desc())
    
    res = await db.execute(stmt)
    transactions = res.scalars().all()

    from app.services.invoice_service import InvoiceService

    history = []
    for tx in transactions:
        inv_num = getattr(tx, "invoice_number", None) or InvoiceService.generate_invoice_number(str(tx.id))
        history.append({
            "id": str(tx.id),
            "invoice_number": inv_num,
            "amount": tx.amount,
            "currency": tx.currency,
            "paid_at": tx.updated_at.isoformat() if tx.updated_at else tx.created_at.isoformat(),
            "is_all_access": tx.is_all_access,
            "purchased_modules": tx.purchased_modules or [],
            "billing_cycle": tx.billing_cycle or "monthly",
            "razorpay_payment_id": tx.razorpay_payment_id
        })

    return {"history": history}


@router.get("/invoices/{transaction_id}")
async def get_invoice_details(
    transaction_id: str,
    current_user: User = Depends(get_current_user),
    shop: Shop = Depends(get_current_shop_context),
    db: AsyncSession = Depends(get_db)
):
    """Get details for a specific invoice/transaction."""
    from fastapi.responses import HTMLResponse
    from app.services.invoice_service import InvoiceService

    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    # Fetch transaction
    try:
        tx_uuid = uuid.UUID(transaction_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid transaction ID format")

    stmt = select(PaymentTransaction).where(PaymentTransaction.id == tx_uuid)
    result = await db.execute(stmt)
    tx = result.scalar_one_or_none()

    if not shop and current_user.role != "super_admin":
        raise HTTPException(status_code=403, detail="Not authorized to view this invoice")

    shop_name = shop.name if shop else "SmartMenu Store"
    inv_data = InvoiceService.build_invoice_data(
        transaction=tx,
        user_email=current_user.email,
        shop_name=shop_name
    )

    html_content = InvoiceService.render_invoice_html(inv_data)
    return HTMLResponse(content=html_content)


@router.post("/check-expirations")
async def check_and_notify_expirations(
    db: AsyncSession = Depends(get_db)
):
    """System background routine to check expiring and expired subscriptions and dispatch email alerts."""
    from app.services.email_service import EmailService

    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")

    # Query all active or recently ended subscriptions
    stmt = select(Subscription, Shop, User).join(
        Shop, Subscription.shop_id == Shop.id
    ).join(
        User, Shop.user_id == User.id
    )

    results = await db.execute(stmt)
    rows = results.all()

    email_svc = EmailService()
    notifications_sent = 0

    for sub, shop, user in rows:
        if sub.last_expiry_notification_date == today_str:
            continue # Already notified today

        raw_expirations = dict(getattr(sub, "module_expirations", {}) or {})
        expiring_soon_mods = []
        expired_mods = []
        min_days_left = 999

        for mod, exp_val in raw_expirations.items():
            if not exp_val:
                continue
            try:
                dt = datetime.fromisoformat(exp_val.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                days_left = (dt - now).days

                if 0 <= days_left <= 3:
                    expiring_soon_mods.append(mod)
                    min_days_left = min(min_days_left, days_left)
                elif days_left < 0 and days_left > -7: # Expired within last week
                    expired_mods.append(mod)
            except Exception:
                pass

        if expiring_soon_mods:
            await email_svc.send_subscription_expiring_email(
                user.email, shop.name, max(0, min_days_left), expiring_soon_mods
            )
            sub.last_expiry_notification_date = today_str
            notifications_sent += 1
        elif expired_mods:
            await email_svc.send_subscription_expired_email(
                user.email, shop.name, expired_mods
            )
            sub.last_expiry_notification_date = today_str
            notifications_sent += 1

    await db.commit()
    return {"status": "success", "notifications_sent": notifications_sent}
