import hmac
import hashlib
import uuid
import json
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database.session import get_db
from app.models.shop import Shop
from app.models.subscription import Subscription, PaymentTransaction
from app.core.config import get_settings
from app.core.deps import get_current_user
from app.models.user import User

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

# Add-on prices based on frontend UI and menu_landing
MODULE_PRICES = {
    'online-orders': 129,
    'new-member': 99,
    'member-count': 99,
    'member-details': 129,
    'search-data': 69,
    'custom-theme': 69,
    'analytics-advanced-filters': 59,
    'analytics-customer-insights': 59,
}
ALL_ACCESS_PRICE = 399


class CreateOrderRequest(BaseModel):
    is_all_access: bool
    selected_modules: List[str]
    billing_cycle: Optional[str] = "monthly"


class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


@router.post("/create-order")
async def create_order(
    request: CreateOrderRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Creates a Razorpay order for the selected subscription modules."""
    
    # Calculate base amount on backend
    base_amount = 0.0
    if request.is_all_access:
        base_amount = float(ALL_ACCESS_PRICE)
    else:
        for mod in request.selected_modules:
            if mod in MODULE_PRICES:
                base_amount += float(MODULE_PRICES[mod])
                
    if request.billing_cycle == "yearly":
        base_amount = round(base_amount * 10.0, 2)  # 2 months free!

    if base_amount == 0:
        raise HTTPException(status_code=400, detail="Total amount cannot be zero for subscription.")

    # Calculate 3% Payment Gateway Fee + 18% GST on PG Fee
    pg_fee = round(base_amount * 0.03, 2)
    gst_on_fee = round(pg_fee * 0.18, 2)
    final_total = round(base_amount + pg_fee + gst_on_fee, 2)

    # Get user's shop
    stmt = select(Shop).where(Shop.user_id == current_user.id)
    result = await db.execute(stmt)
    shop = result.scalar_one_or_none()
    
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    amount_in_paise = int(round(final_total * 100))  # Razorpay accepts subunits (paise)

    # 1. Mock / Fallback Mode
    if settings.MOCK_PAYMENT_MODE:
        mock_order_id = f"order_mock_{uuid.uuid4().hex[:14]}"
        
        transaction = PaymentTransaction(
            shop_id=shop.id,
            razorpay_order_id=mock_order_id,
            amount=final_total,
            currency="INR",
            status="created",
            is_all_access=request.is_all_access,
            purchased_modules=request.selected_modules,
            billing_cycle=request.billing_cycle or "monthly"
        )
        db.add(transaction)
        await db.commit()
        
        return {
            "order_id": mock_order_id,
            "base_amount": base_amount,
            "pg_fee": pg_fee,
            "gst_on_fee": gst_on_fee,
            "final_total": final_total,
            "amount": amount_in_paise,
            "currency": "INR",
            "mock_mode": True,
            "key": settings.RAZORPAY_KEY_ID or "rzp_test_mock"
        }

    # 2. Real Razorpay Mode
    try:
        order_data = {
            "amount": amount_in_paise,
            "currency": "INR",
            "receipt": f"sub_rcpt_{shop.id.hex[:10]}_{int(datetime.now().timestamp())}",
            "notes": {
                "shop_id": str(shop.id),
                "is_all_access": "true" if request.is_all_access else "false",
                "billing_cycle": request.billing_cycle or "monthly",
                "base_amount": str(base_amount),
                "pg_fee": str(pg_fee),
                "gst_on_fee": str(gst_on_fee)
            }
        }
        order = razorpay_client.order.create(data=order_data)
        
        # Save pending transaction
        transaction = PaymentTransaction(
            shop_id=shop.id,
            razorpay_order_id=order['id'],
            amount=final_total,
            currency="INR",
            status="created",
            is_all_access=request.is_all_access,
            purchased_modules=request.selected_modules,
            billing_cycle=request.billing_cycle or "monthly"
        )
        db.add(transaction)
        await db.commit()
        
        return {
            "order_id": order['id'],
            "base_amount": base_amount,
            "pg_fee": pg_fee,
            "gst_on_fee": gst_on_fee,
            "final_total": final_total,
            "amount": order['amount'],
            "currency": order['currency'],
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
    
    # Update or Create Subscription
    stmt = select(Subscription).where(Subscription.shop_id == transaction.shop_id)
    result = await db.execute(stmt)
    subscription = result.scalar_one_or_none()
    
    if not subscription:
        subscription = Subscription(shop_id=transaction.shop_id)
        db.add(subscription)
        
    subscription.is_active = True
    
    existing_mods = list(subscription.active_modules or [])
    if getattr(subscription, "is_trial", False):
        # If shop was previously on initial free trial, start paid module list fresh
        existing_mods = []
        
    purchased_mods = list(transaction.purchased_modules or [])
    
    # ACCUMULATE & MERGE MODULES SO PREVIOUS SUBSCRIPTIONS ARE NOT REMOVED
    if transaction.is_all_access:
        subscription.is_all_access = True
        subscription.active_modules = ALL_MARKETPLACE_MODULES
    else:
        if not getattr(subscription, "is_all_access", False):
            subscription.is_all_access = False
            
        # Merge existing active modules and newly purchased modules without duplicates
        merged_modules = list(dict.fromkeys(existing_mods + purchased_mods))
        subscription.active_modules = merged_modules
        
    subscription.is_trial = False
    
    now = datetime.now(timezone.utc)
    duration_days = 365 if getattr(transaction, "billing_cycle", "monthly") == "yearly" else 30
    
    # Granular per-module expiration calculation
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

    # Ensure all currently active modules preserve their existing expiration in the dictionary
    all_current_active = list(subscription.active_modules or [])
    if getattr(subscription, "is_all_access", False):
        all_current_active = ALL_MARKETPLACE_MODULES
        
    was_trial = getattr(subscription, "is_trial", False)
    for mod in all_current_active:
        if mod not in module_expirations:
            if existing_period_end and existing_period_end > now and not was_trial:
                module_expirations[mod] = existing_period_end
            else:
                module_expirations[mod] = now + timedelta(days=duration_days)

    # Modules to update expiration for in this transaction
    modules_to_update = ALL_MARKETPLACE_MODULES if transaction.is_all_access else (transaction.purchased_modules or [])
    
    for mod in modules_to_update:
        prev_exp = module_expirations.get(mod)
        if not prev_exp and existing_period_end and existing_period_end > now and not was_trial:
            prev_exp = existing_period_end

        if prev_exp and prev_exp > now and not was_trial:
            # Module was ALREADY active -> Sequential extension (add +30 days to existing expiration)
            module_expirations[mod] = prev_exp + timedelta(days=duration_days)
        else:
            # Brand NEW module or trial module -> 30 days from today!
            module_expirations[mod] = now + timedelta(days=duration_days)

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
    
    return {
        "status": "success",
        "message": "Subscription activated successfully"
    }


ALL_MARKETPLACE_MODULES = [
    "online-orders", "new-member", "member-count", "member-details", 
    "search-data", "custom-theme", "analytics-advanced-filters", "analytics-customer-insights"
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
    active_mods_list = subscription.active_modules if subscription.active_modules else ALL_MARKETPLACE_MODULES
    
    # Calculate fallback expiration date for active modules not explicitly listed in raw_exp
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

    for mod in active_mods_list:
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
        formatted_module_expirations[mod] = {
            "expires_at": mod_exp_dt.isoformat() if mod_exp_dt else None,
            "days_left": mod_days_left
        }

    return {
        "is_active": is_active,
        "is_all_access": subscription.is_all_access if is_active else False,
        "active_modules": (subscription.active_modules if subscription.active_modules else ALL_MARKETPLACE_MODULES) if is_active else [],
        "module_expirations": formatted_module_expirations if is_active else {},
        "current_period_end": subscription.current_period_end,
        "is_trial": is_trial,
        "is_expired": is_expired,
        "is_grace_period": is_grace_period,
        "grace_days_left": grace_days_left,
        "days_left": days_left,
        "free_trial_days": settings.FREE_TRIAL_DAYS,
        "grace_period_days": settings.GRACE_PERIOD_DAYS,
        "status_message": status_msg
    }


@router.get("/current")
async def get_current_subscription(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get active subscription details for the current user's shop including trial & grace period status."""
    stmt = select(Shop).where(Shop.user_id == current_user.id)
    result = await db.execute(stmt)
    shop = result.scalar_one_or_none()
    
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
        
    return await get_shop_subscription_status(shop, db)
