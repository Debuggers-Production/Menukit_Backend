"""Customer API endpoints."""

import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as redis

from app.database.session import get_db
from app.database.redis import get_redis
from app.schemas.customer import (
    MobileVerifyRequest, MobileVerifyResponse, OTPVerifyRequest, OTPVerifyResponse,
    CustomerRegisterRequest, CustomerResponse
)
from app.services.customer_service import CustomerService
from app.services.otp_service import OTPService
from app.services.sms_service import sms_service
from app.services.membership_service import MembershipService
from app.services.whatsapp_service import WhatsAppClient
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/customers", tags=["Customers"])
logger = logging.getLogger(__name__)


@router.post("/verify-mobile", response_model=MobileVerifyResponse)
async def verify_mobile(
    data: MobileVerifyRequest,
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis)
):
    """Generate and send OTP for mobile verification, or bypass if valid token provided."""
    from app.core.security import verify_customer_token
    
    # 1. Check if valid token matches the mobile number
    if data.token:
        token_mobile = verify_customer_token(data.token)
        if token_mobile and token_mobile == data.mobile_number:
            # Token is valid! Bypass OTP and return customer status
            customer_service = CustomerService(db)
            membership_service = MembershipService(db)
            customer = await customer_service.get_customer_by_mobile(data.mobile_number)
            
            response = MobileVerifyResponse(otp_required=False, message="Verified via token")
            
            if data.shop_id:
                await membership_service.log_event(data.shop_id, "token_verified")
                
            if customer:
                response.is_global_customer = True
                response.customer_name = customer.name
                response.delivery_address = customer.delivery_address
                
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

    # 2. Token invalid or missing, proceed with SMS OTP generation via MSG91
    verification_id = await sms_service.send_otp(data.mobile_number, country_code=data.country_code)
    if not verification_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send OTP via SMS. Please try again later."
        )
    
    # Store the verificationId in Redis linked to the mobile number (and clean number fallback)
    redis_key = f"m_v_id:{data.mobile_number}"
    clean_num = "".join(c for c in str(data.mobile_number) if c.isdigit())
    await redis_client.setex(redis_key, 300, verification_id) # Valid for 5 mins
    if clean_num and clean_num != data.mobile_number:
        await redis_client.setex(f"m_v_id:{clean_num}", 300, verification_id)

    # Fallback/Debug print
    logger.info(f"📱 OTP Request sent for {data.mobile_number} | Verification ID: {verification_id}")

    return MobileVerifyResponse(otp_required=True, message="OTP sent successfully")


@router.post("/verify-otp", response_model=OTPVerifyResponse)
async def verify_otp(
    data: OTPVerifyRequest,
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis)
):
    """Verify OTP and return customer/membership status."""
    redis_key = f"m_v_id:{data.mobile_number}"
    verification_id_bytes = await redis_client.get(redis_key)
    
    # Try sanitized phone key if not found with raw input
    if not verification_id_bytes:
        clean_num = "".join(c for c in str(data.mobile_number) if c.isdigit())
        if clean_num:
            verification_id_bytes = await redis_client.get(f"m_v_id:{clean_num}")

    is_valid = False
    if sms_service.mock_mode and data.code == "123456":
        logger.info(f"🔑 Dev bypass OTP used for {data.mobile_number} (Mock Mode Active)")
        is_valid = True
    elif verification_id_bytes:
        verification_id = verification_id_bytes.decode('utf-8') if isinstance(verification_id_bytes, bytes) else str(verification_id_bytes)
        is_valid = await sms_service.verify_otp(verification_id, data.code, mobile_number=data.mobile_number)
    else:
        logger.error(f"❌ OTP verification failed for {data.mobile_number}: Verification ID expired or not found in Redis (Key: {redis_key})")

    if not is_valid:
        if verification_id_bytes:
            logger.error(f"❌ OTP verification failed for {data.mobile_number}: Code '{data.code}' rejected by MSG91")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OTP code."
        )
    
    if is_valid and verification_id_bytes:
        # Clear from redis after successful verification
        await redis_client.delete(redis_key)

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
        response.delivery_address = customer.delivery_address
        
        from app.core.security import create_customer_token
        response.access_token = create_customer_token(customer.mobile_number)
        
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
                # Send Notification
                await NotificationService(db).create_notification(
                    shop_id=data.shop_id,
                    type="NEW_CUSTOMER",
                    title="New Customer Joined!",
                    message=f"Customer {customer.name} verified their number.",
                    metadata={"customer_id": str(customer.id)}
                )

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
        # Send Notification
        await NotificationService(db).create_notification(
            shop_id=data.shop_id,
            type="NEW_CUSTOMER",
            title="New Customer Registered!",
            message=f"Customer {customer.name} has joined your shop.",
            metadata={"customer_id": str(customer.id)}
        )
        
    from app.core.security import create_customer_token
    
    return CustomerResponse(
        id=customer.id,
        name=customer.name,
        mobile_number=customer.mobile_number,
        created_at=customer.created_at,
        access_token=create_customer_token(customer.mobile_number),
        delivery_address=customer.delivery_address
    )
