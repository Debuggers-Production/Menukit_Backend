import hmac
import hashlib
import uuid
import json
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database.session import get_db
from app.models.shop import Shop
from app.models.subscription import Subscription, PaymentTransaction
from app.core.config import get_settings
from app.core.deps import get_current_user
from app.models.user import User

import razorpay

router = APIRouter()
settings = get_settings()

# Initialize Razorpay Client (only if not mocked and keys exist)
razorpay_client = None
if not settings.MOCK_PAYMENT_MODE and settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET:
    razorpay_client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

# Hardcoded feature prices based on frontend UI
MODULE_PRICES = {
    'new-member': 100,
    'member-details': 150,
    'search-data': 50,
    'custom-theme': 50,
    'analytics-advanced-filters': 30,
    'analytics-customer-insights': 30,
}
ALL_ACCESS_PRICE = 299


class CreateOrderRequest(BaseModel):
    is_all_access: bool
    selected_modules: List[str]


class VerifyPaymentRequest(BaseModel):
    razorpay_payment_id: str
    razorpay_order_id: str
    razorpay_signature: str


@router.post("/create-order")
async def create_order(
    request: CreateOrderRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Creates a Razorpay order for the selected subscription modules."""
    
    # Calculate amount on the backend to prevent frontend tampering
    total_amount = 0
    if request.is_all_access:
        total_amount = ALL_ACCESS_PRICE
    else:
        for mod in request.selected_modules:
            if mod in MODULE_PRICES:
                total_amount += MODULE_PRICES[mod]
                
    if total_amount == 0:
        raise HTTPException(status_code=400, detail="Total amount cannot be zero for payment.")

    # Get user's shop
    stmt = select(Shop).where(Shop.user_id == current_user.id)
    result = await db.execute(stmt)
    shop = result.scalar_one_or_none()
    
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    amount_in_paise = int(total_amount * 100) # Razorpay accepts amount in subunits
    
    # 1. Mock Mode
    if settings.MOCK_PAYMENT_MODE or not razorpay_client:
        mock_order_id = f"order_mock_{uuid.uuid4().hex[:14]}"
        
        # Save pending transaction
        transaction = PaymentTransaction(
            shop_id=shop.id,
            razorpay_order_id=mock_order_id,
            amount=total_amount,
            currency="INR",
            status="created",
            is_all_access=request.is_all_access,
            purchased_modules=request.selected_modules
        )
        db.add(transaction)
        await db.commit()
        
        return {
            "order_id": mock_order_id,
            "amount": amount_in_paise,
            "currency": "INR",
            "mock_mode": True
        }

    # 2. Real Razorpay Mode
    try:
        order_data = {
            "amount": amount_in_paise,
            "currency": "INR",
            "receipt": f"receipt_{shop.id}_{int(datetime.now().timestamp())}",
            "notes": {
                "shop_id": str(shop.id),
                "is_all_access": "true" if request.is_all_access else "false"
            }
        }
        order = razorpay_client.order.create(data=order_data)
        
        # Save pending transaction
        transaction = PaymentTransaction(
            shop_id=shop.id,
            razorpay_order_id=order['id'],
            amount=total_amount,
            currency="INR",
            status="created",
            is_all_access=request.is_all_access,
            purchased_modules=request.selected_modules
        )
        db.add(transaction)
        await db.commit()
        
        return {
            "order_id": order['id'],
            "amount": order['amount'],
            "currency": order['currency'],
            "mock_mode": False,
            "key": settings.RAZORPAY_KEY_ID
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create order: {str(e)}")


@router.post("/verify")
async def verify_payment(
    request: VerifyPaymentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Verifies payment signature and activates the subscription."""
    
    stmt = select(PaymentTransaction).where(PaymentTransaction.razorpay_order_id == request.razorpay_order_id)
    result = await db.execute(stmt)
    transaction = result.scalar_one_or_none()
    
    if not transaction:
        raise HTTPException(status_code=404, detail="Order not found")
        
    if transaction.status == "success":
        return {"status": "already_verified"}

    # Verify Signature
    is_valid = False
    
    if request.razorpay_order_id.startswith("order_mock_"):
        # Accept mock payments
        is_valid = True
    else:
        if not razorpay_client:
            raise HTTPException(status_code=500, detail="Razorpay is not configured")
            
        try:
            params_dict = {
                'razorpay_order_id': request.razorpay_order_id,
                'razorpay_payment_id': request.razorpay_payment_id,
                'razorpay_signature': request.razorpay_signature
            }
            razorpay_client.utility.verify_payment_signature(params_dict)
            is_valid = True
        except Exception as e:
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
    subscription.is_all_access = transaction.is_all_access
    subscription.active_modules = transaction.purchased_modules
    subscription.current_period_end = datetime.now(timezone.utc) + timedelta(days=30)
    
    await db.commit()
    
    return {
        "status": "success",
        "message": "Subscription activated successfully"
    }

@router.get("/current")
async def get_current_subscription(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get the active subscription details for the current user's shop."""
    stmt = select(Shop).where(Shop.user_id == current_user.id)
    result = await db.execute(stmt)
    shop = result.scalar_one_or_none()
    
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
        
    stmt = select(Subscription).where(Subscription.shop_id == shop.id)
    result = await db.execute(stmt)
    subscription = result.scalar_one_or_none()
    
    if not subscription:
        return {
            "is_active": False,
            "is_all_access": False,
            "active_modules": []
        }
        
    return {
        "is_active": subscription.is_active,
        "is_all_access": subscription.is_all_access,
        "active_modules": subscription.active_modules,
        "current_period_end": subscription.current_period_end
    }
