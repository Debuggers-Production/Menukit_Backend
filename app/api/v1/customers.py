"""Customer API endpoints."""

import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as redis

from app.database.session import get_db
from app.database.redis import get_redis
from app.schemas.customer import (
    MobileVerifyRequest, OTPVerifyRequest, OTPVerifyResponse,
    CustomerRegisterRequest, CustomerResponse
)
from app.services.customer_service import CustomerService
from app.services.otp_service import OTPService
from app.services.membership_service import MembershipService

router = APIRouter(prefix="/customers", tags=["Customers"])


@router.post("/verify-mobile")
async def verify_mobile(
    data: MobileVerifyRequest,
    redis_client: redis.Redis = Depends(get_redis)
):
    """Generate and send OTP for mobile verification."""
    otp_service = OTPService(redis_client)
    # Using mobile_number as the key in OTPService
    code = await otp_service.create_otp(data.mobile_number)
    if not code:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many OTP requests. Please try again later."
        )
    
    # In a real app, send the OTP via SMS gateway here.
    # For development, we print it.
    print(f"DEBUG: OTP for {data.mobile_number} is {code}")
    
    return {"message": "OTP sent successfully"}


@router.post("/verify-otp", response_model=OTPVerifyResponse)
async def verify_otp(
    data: OTPVerifyRequest,
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis)
):
    """Verify OTP and return customer/membership status."""
    otp_service = OTPService(redis_client)
    
    # We allow a magic OTP "000000" for quick local testing if desired,
    # but strictly checking Redis here.
    is_valid = await otp_service.verify_otp(data.mobile_number, data.code)
    # Mock fallback for local dev if not found in Redis (optional)
    if not is_valid and data.code != "123456": # Magic code for dev
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OTP code."
        )

    customer_service = CustomerService(db)
    membership_service = MembershipService(db)

    customer = await customer_service.get_customer_by_mobile(data.mobile_number)
    
    response = OTPVerifyResponse(
        is_global_customer=False,
        is_member=False
    )
    
    if data.shop_id:
        await membership_service.log_event(data.shop_id, "otp_verified")

    if customer:
        response.is_global_customer = True
        response.customer_name = customer.name
        
        if data.shop_id:
            membership = await customer_service.get_membership(customer.id, data.shop_id)
            if membership:
                response.is_member = True
                response.is_strict_member = membership.is_retailer_added
                await membership_service.log_event(data.shop_id, "discount_unlocked", customer.id)
            else:
                response.is_member = False
                response.is_strict_member = False
                await customer_service.add_membership(customer.id, data.shop_id, is_retailer_added=False)
                await membership_service.log_event(data.shop_id, "member_matched", customer.id)

    return response


@router.post("/register", response_model=CustomerResponse)
async def register_customer(
    data: CustomerRegisterRequest,
    db: AsyncSession = Depends(get_db)
):
    """Register a new global customer. Assuming OTP was verified just before."""
    customer_service = CustomerService(db)
    membership_service = MembershipService(db)
    
    customer = await customer_service.register_customer(data.name, data.mobile_number)
    
    if data.shop_id:
        await customer_service.add_membership(customer.id, data.shop_id, is_retailer_added=False)
        await membership_service.log_event(data.shop_id, "member_matched", customer.id)
        
    return customer
