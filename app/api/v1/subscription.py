import hmac
import hashlib
import uuid
import json
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


class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
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
            billing_cycle=request.billing_cycle or "monthly"
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
            "key": settings.RAZORPAY_KEY_ID or "rzp_test_mock"
        }

    # 2. Real Razorpay Mode
    try:
        order_data = {
            "amount": amount_subunits,
            "currency": currency,
            "receipt": f"sub_rcpt_{shop.id.hex[:10]}_{int(datetime.now().timestamp())}",
            "notes": {
                "shop_id": str(shop.id),
                "is_all_access": "true" if request.is_all_access else "false",
                "billing_cycle": request.billing_cycle or "monthly",
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
            billing_cycle=request.billing_cycle or "monthly"
        )
        db.add(transaction)
        await db.commit()
        
        return {
            "order_id": order['id'],
            "base_amount": calc["base_subtotal"],
            "pg_fee": calc["pg_fee"],
            "gst_on_fee": calc["gst_on_fee"],
            "final_total": final_total,
            "amount": order['amount'],
            "currency": order['currency'],
            "currency_symbol": calc["currency_symbol"],
            "mock_mode": False,
            "key": settings.RAZORPAY_KEY_ID
        }
    except Exception as e:
        print(f"Razorpay order creation error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create Razorpay order: {str(e)}")


@router.post("/verify")
async def verify_payment(
    request: VerifyPaymentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Verifies Razorpay payment signature and activates the subscription."""
    
    stmt = select(PaymentTransaction).where(PaymentTransaction.razorpay_order_id == request.razorpay_order_id)
    result = await db.execute(stmt)
    transaction = result.scalar_one_or_none()
    
    if not transaction:
        raise HTTPException(status_code=404, detail="Order transaction not found")
        
    if transaction.status == "success":
        return {"status": "already_verified", "message": "Subscription active"}

    is_valid = False
    
    if settings.MOCK_PAYMENT_MODE and request.razorpay_order_id.startswith("order_mock_"):
        # Accept mock payments
        is_valid = True
    else:
        if not razorpay_client:
            raise HTTPException(status_code=500, detail="Razorpay client is not configured")
            
        try:
            params_dict = {
                'razorpay_order_id': request.razorpay_order_id,
                'razorpay_payment_id': request.razorpay_payment_id,
                'razorpay_signature': request.razorpay_signature
            }
            razorpay_client.utility.verify_payment_signature(params_dict)
            is_valid = True
        except Exception as e:
            print(f"Razorpay signature verification failed: {e}")
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
        # Only true if they actually have a valid unexpired all-access payment transaction
        stmt_aa = select(PaymentTransaction).where(
            PaymentTransaction.shop_id == subscription.shop_id,
            PaymentTransaction.status == "success",
            PaymentTransaction.is_all_access == True
        )
        aa_res = await db.execute(stmt_aa)
        subscription.is_all_access = aa_res.scalars().first() is not None

    subscription.is_trial = False

    # Save serialized ISO strings
    subscription.module_expirations = {
        k: v.isoformat() for k, v in module_expirations.items()
    }
    
    # Global subscription end is max among all active module expiration dates
    if module_expirations:
        subscription.current_period_end = max(module_expirations.values())
    else:
        subscription.current_period_end = now + timedelta(days=duration_days)
            
    await db.commit()
    
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
    "online-orders", "new-member", "member-count", "member-details", 
    "search-data", "custom-theme", "analytics-advanced", "hide-discovery-badge"
]


async def get_shop_subscription_status(shop: Shop, db: AsyncSession) -> dict:
    """Helper to compute shop subscription status including trial, grace period, and mock overrides."""
    stmt = select(Subscription).where(Subscription.shop_id == shop.id)
    result = await db.execute(stmt)
    subscription = result.scalar_one_or_none()
    
    now = datetime.now(timezone.utc)
    
    # 1. If shop has no subscription yet, create default 1-Month Free Trial Subscription!
    if not subscription:
        created_at = shop.created_at or now
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        trial_end = created_at + timedelta(days=settings.FREE_TRIAL_DAYS)
        
        subscription = Subscription(
            shop_id=shop.id,
            is_active=True,
            is_all_access=True,
            is_trial=True,
            active_modules=ALL_MARKETPLACE_MODULES,
            current_period_end=trial_end
        )
        db.add(subscription)
        await db.commit()
        await db.refresh(subscription)

    # 2. Expiration & Grace Period Calculations
    period_end = subscription.current_period_end
    if period_end and period_end.tzinfo is None:
        period_end = period_end.replace(tzinfo=timezone.utc)

    if not period_end:
        created_at = subscription.created_at or now
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        period_end = created_at + timedelta(days=settings.FREE_TRIAL_DAYS)

    grace_end = period_end + timedelta(days=settings.GRACE_PERIOD_DAYS)

    days_left = max(0, (period_end - now).days)
    grace_days_left = max(0, (grace_end - now).days)

    is_trial = getattr(subscription, "is_trial", False)
    is_active = True
    is_expired = False
    is_grace_period = False
    status_msg = ""

    if now <= period_end:
        is_active = True
        is_expired = False
        is_grace_period = False
        status_msg = f"Free Trial active ({days_left} days left)" if is_trial else f"Active subscription ({days_left} days left)"
    elif now <= grace_end:
        is_active = True  # Grace period allows continued use with banner warning
        is_expired = False
        is_grace_period = True
        status_msg = f"Subscription ended. Grace period active ({grace_days_left} days left)."
    else:
        is_active = False
        is_expired = True
        is_grace_period = False
        status_msg = "Subscription ended. Features locked. Please renew to continue."

    # Environment Mock Override for UI Banner Testing
    mock_state = (getattr(settings, "MOCK_SUBSCRIPTION_STATE", "none") or "none").lower()
    if mock_state == "ending_soon":
        is_active = True
        is_expired = False
        is_grace_period = False
        days_left = 2
        status_msg = "Mock: Free Trial / Subscription Ending Soon (2 days left)"
    elif mock_state == "grace_period":
        is_active = True
        is_expired = False
        is_grace_period = True
        days_left = 0
        grace_days_left = 4
        status_msg = "Mock: Grace Period Active (4 days left)"
    elif mock_state == "expired":
        is_active = False
        is_expired = True
        is_grace_period = False
        days_left = 0
        grace_days_left = 0
        status_msg = "Mock: Subscription Ended. Features Locked."

    if subscription.is_active != is_active and mock_state == "none":
        subscription.is_active = is_active
        await db.commit()

    # Format per-module expiration details for granular frontend display
    raw_exp = dict(getattr(subscription, "module_expirations", {}) or {})
    formatted_module_expirations = {}
    
    # Re-evaluate which modules are actually active based on granular expiration
    tracked_dts = []
    for v in raw_exp.values():
        if isinstance(v, str):
            try:
                dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                tracked_dts.append(dt)
            except Exception:
                pass
        elif isinstance(v, datetime):
            dt = v
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            tracked_dts.append(dt)

    fallback_dt = min(tracked_dts) if tracked_dts else period_end

    dynamic_active_modules = []
    
    db_active_mods = subscription.active_modules if subscription.active_modules else ALL_MARKETPLACE_MODULES
    
    for mod in db_active_mods:
        mod_exp_str = raw_exp.get(mod)
        mod_exp_dt = None
        if mod_exp_str:
            try:
                mod_exp_dt = datetime.fromisoformat(mod_exp_str.replace("Z", "+00:00"))
            except Exception:
                mod_exp_dt = fallback_dt
        else:
            mod_exp_dt = fallback_dt
            
        if mod_exp_dt and mod_exp_dt.tzinfo is None:
            mod_exp_dt = mod_exp_dt.replace(tzinfo=timezone.utc)
            
        mod_days_left = max(0, (mod_exp_dt - now).days) if mod_exp_dt else days_left
        
        # Consider grace period. If global is_active is True due to grace period, we shouldn't necessarily
        # lock modules individually, but we should check if this specific module has grace period.
        grace_dt = mod_exp_dt + timedelta(days=settings.GRACE_PERIOD_DAYS) if mod_exp_dt else grace_end
        mod_grace_days_left = max(0, (grace_dt - now).days)
        
        is_mod_active = mod_days_left > 0 or mod_grace_days_left > 0
        
        if is_mod_active and is_active:
            dynamic_active_modules.append(mod)
            
        formatted_module_expirations[mod] = {
            "expires_at": mod_exp_dt.isoformat() if mod_exp_dt else None,
            "days_left": mod_days_left
        }

    is_actual_all_access = is_trial
    if not is_trial and getattr(subscription, "is_all_access", False):
        stmt_aa = select(PaymentTransaction).where(
            PaymentTransaction.shop_id == shop.id,
            PaymentTransaction.status == "success",
            PaymentTransaction.is_all_access == True
        )
        aa_res = await db.execute(stmt_aa)
        is_actual_all_access = aa_res.scalars().first() is not None

    # Calculate earliest remaining days among active modules
    active_days_list = [
        info["days_left"] for mod, info in formatted_module_expirations.items()
        if mod in dynamic_active_modules and info.get("days_left") is not None
    ]
    core_days_left = min(active_days_list) if active_days_list else days_left

    # If core modules / trial are expiring within 5 days, use core_days_left so banner intimates expiry
    effective_days_left = core_days_left if (core_days_left <= 5 or is_trial) else days_left

    return {
        "is_active": is_active,
        "is_all_access": is_actual_all_access if is_active else False,
        "active_modules": dynamic_active_modules if is_active else [],
        "module_expirations": formatted_module_expirations if is_active else {},
        "current_period_end": subscription.current_period_end,
        "is_trial": is_trial,
        "is_expired": is_expired,
        "is_grace_period": is_grace_period,
        "grace_days_left": grace_days_left,
        "days_left": effective_days_left,
        "core_days_left": core_days_left,
        "max_days_left": days_left,
        "has_expiring_modules": core_days_left <= 5,
        "free_trial_days": settings.FREE_TRIAL_DAYS,
        "grace_period_days": settings.GRACE_PERIOD_DAYS,
        "status_message": status_msg
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
