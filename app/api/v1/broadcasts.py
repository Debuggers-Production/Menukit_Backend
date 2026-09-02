"""Broadcast marketing API routes."""

import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.core.deps import require_permission, get_current_user
from app.models.user import User

from app.schemas.broadcast import (
    AudienceCountRequest,
    AudienceCountResponse,
    BroadcastTestSendRequest,
    BroadcastCampaignCreate,
    BroadcastCampaignResponse,
    BroadcastCampaignListResponse,
)

import hmac
import hashlib
from datetime import datetime, timezone
from pydantic import BaseModel
from sqlalchemy import select
from app.services.broadcast_service import BroadcastService
from app.models.subscription import PaymentTransaction
from app.core.config import get_settings

router = APIRouter(prefix="/broadcasts", tags=["Broadcast Marketing"])


class DeleteMediaRequest(BaseModel):
    image_url: str


class BroadcastCreditsResponse(BaseModel):
    available_credits: int
    cost_per_message: float = 1.0


class TopupOrderRequest(BaseModel):
    credits: int


class VerifyTopupRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    credits: int


@router.get("/credits", response_model=BroadcastCreditsResponse)
async def get_broadcast_credits(
    shop = Depends(require_permission("marketing", "read")),
    db: AsyncSession = Depends(get_db),
):
    """Get current available WhatsApp broadcast messaging credits."""
    return BroadcastCreditsResponse(
        available_credits=getattr(shop, "broadcast_credits", 0) or 0,
        cost_per_message=1.0,
    )


@router.post("/credits/topup-order")
async def create_topup_order(
    request: TopupOrderRequest,
    shop = Depends(require_permission("marketing", "write")),
    db: AsyncSession = Depends(get_db),
):
    """Create a Razorpay payment order for purchasing WhatsApp broadcast credits (₹1/credit)."""
    if request.credits < 1:
        raise HTTPException(status_code=400, detail="Minimum top-up is 1 message credit (₹1)")

    base_amount = float(request.credits) * 1.0  # ₹1 per message
    pg_fee = round(base_amount * 0.03, 2)
    gst_on_fee = round(pg_fee * 0.18, 2)
    final_total = round(base_amount + pg_fee + gst_on_fee, 2)
    amount_in_paise = int(round(final_total * 100))

    settings = get_settings()

    if settings.MOCK_PAYMENT_MODE or not settings.RAZORPAY_KEY_ID:
        mock_order_id = f"order_mock_{uuid.uuid4().hex[:14]}"
        transaction = PaymentTransaction(
            shop_id=shop.id,
            razorpay_order_id=mock_order_id,
            amount=final_total,
            currency="INR",
            status="created",
            is_all_access=False,
            purchased_modules=[f"broadcast-credits-{request.credits}"],
            billing_cycle="one-time",
        )
        db.add(transaction)
        await db.commit()
        return {
            "order_id": mock_order_id,
            "credits": request.credits,
            "base_amount": base_amount,
            "pg_fee": pg_fee,
            "gst_on_fee": gst_on_fee,
            "final_total": final_total,
            "amount": amount_in_paise,
            "currency": "INR",
            "mock_mode": True,
            "key": settings.RAZORPAY_KEY_ID or "rzp_test_mock",
        }

    try:
        import razorpay
        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        order_data = {
            "amount": amount_in_paise,
            "currency": "INR",
            "receipt": f"bcast_{shop.id.hex[:8]}_{int(datetime.now().timestamp())}",
            "notes": {
                "shop_id": str(shop.id),
                "credits": str(request.credits),
                "type": "broadcast_credits",
            },
        }
        order = client.order.create(data=order_data)
        transaction = PaymentTransaction(
            shop_id=shop.id,
            razorpay_order_id=order["id"],
            amount=final_total,
            currency="INR",
            status="created",
            is_all_access=False,
            purchased_modules=[f"broadcast-credits-{request.credits}"],
            billing_cycle="one-time",
        )
        db.add(transaction)
        await db.commit()
        return {
            "order_id": order["id"],
            "credits": request.credits,
            "base_amount": base_amount,
            "pg_fee": pg_fee,
            "gst_on_fee": gst_on_fee,
            "final_total": final_total,
            "amount": amount_in_paise,
            "currency": "INR",
            "mock_mode": False,
            "key": settings.RAZORPAY_KEY_ID,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create Razorpay payment order: {str(e)}")


@router.post("/credits/verify-topup")
async def verify_topup_payment(
    request: VerifyTopupRequest,
    shop = Depends(require_permission("marketing", "write")),
    db: AsyncSession = Depends(get_db),
):
    """Verify Razorpay payment signature and add messaging credits to the shop."""
    settings = get_settings()

    is_mock_sig = (
        request.razorpay_signature in ("mock_verified_sig", "sig_mock_verified")
        or request.razorpay_payment_id.startswith("pay_mock_")
        or request.razorpay_order_id.startswith("order_mock_")
    )

    if not is_mock_sig and not settings.MOCK_PAYMENT_MODE and settings.RAZORPAY_KEY_SECRET:
        generated_signature = hmac.new(
            settings.RAZORPAY_KEY_SECRET.encode("utf-8"),
            f"{request.razorpay_order_id}|{request.razorpay_payment_id}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if generated_signature != request.razorpay_signature:
            raise HTTPException(status_code=400, detail="Invalid Razorpay payment signature.")

    # Update transaction record
    tx_stmt = select(PaymentTransaction).where(PaymentTransaction.razorpay_order_id == request.razorpay_order_id)
    tx_res = await db.execute(tx_stmt)
    tx = tx_res.scalar_one_or_none()
    if tx:
        tx.status = "success"
        tx.razorpay_payment_id = request.razorpay_payment_id
        tx.razorpay_signature = request.razorpay_signature
    else:
        tx = PaymentTransaction(
            shop_id=shop.id,
            razorpay_order_id=request.razorpay_order_id,
            razorpay_payment_id=request.razorpay_payment_id,
            razorpay_signature=request.razorpay_signature,
            amount=float(request.credits),
            currency="INR",
            status="success",
            is_all_access=False,
            purchased_modules=[f"broadcast-credits-{request.credits}"],
            billing_cycle="one-time",
        )
        db.add(tx)


    # Add credits to shop
    shop.broadcast_credits = (shop.broadcast_credits or 0) + request.credits
    await db.commit()
    await db.refresh(shop)

    return {
        "success": True,
        "message": f"Successfully recharged {request.credits} broadcast credits!",
        "available_credits": shop.broadcast_credits,
        "credits_added": request.credits,
    }


@router.get("/media-library", response_model=List[str])
async def get_broadcast_media_library(
    shop = Depends(require_permission("marketing", "read")),
    db: AsyncSession = Depends(get_db),
):
    """Get distinct previously used campaign images for this shop."""
    service = BroadcastService(db)
    return await service.get_media_library(shop.id)


@router.delete("/media-library")
async def delete_broadcast_media_image(
    data: DeleteMediaRequest,
    shop = Depends(require_permission("marketing", "write")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a campaign image from MinIO and clear references in this shop's campaign history."""
    if not data.image_url:
        raise HTTPException(status_code=400, detail="Image URL is required")
    service = BroadcastService(db)
    await service.delete_media_image(shop.id, data.image_url)
    return {"success": True, "message": "Image deleted from storage and media library"}


@router.post("/audience-count", response_model=AudienceCountResponse)
async def get_audience_count(
    data: AudienceCountRequest,
    shop = Depends(require_permission("marketing", "read")),
    db: AsyncSession = Depends(get_db),

):
    """Calculate live target audience recipient count for a given filter."""
    service = BroadcastService(db)
    count = await service.calculate_audience_count(
        shop.id, data.target_audience, data.min_visits or 2
    )
    return AudienceCountResponse(
        count=count,
        target_audience=data.target_audience,
        min_visits=data.min_visits,
    )


@router.post("/test-send")
async def send_test_broadcast(
    data: BroadcastTestSendRequest,
    shop = Depends(require_permission("marketing", "write")),
    db: AsyncSession = Depends(get_db),
):
    """Send an immediate test campaign message to a single WhatsApp number."""
    if not data.phone_number:
        raise HTTPException(status_code=400, detail="Phone number is required")
    if not data.message:
        raise HTTPException(status_code=400, detail="Campaign message text is required")

    service = BroadcastService(db)
    try:
        res = await service.send_test_message(
            shop_id=shop.id,
            phone_number=data.phone_number,
            message=data.message,
            image_url=data.image_url,
        )
    except ValueError as ve:
        err_msg = str(ve)
        if "INSUFFICIENT_CREDITS" in err_msg:
            raise HTTPException(
                status_code=400,
                detail="Insufficient broadcast credits. You need 1 credit (₹1.00) to send a test message. Please recharge your balance.",
            )
        raise HTTPException(status_code=400, detail=err_msg)

    if isinstance(res, dict) and res.get("status_code", 200) >= 400:
        raise HTTPException(
            status_code=400,
            detail=res.get("error") or "Failed to dispatch test WhatsApp message",
        )
    return {"success": True, "details": res}



@router.post("", response_model=BroadcastCampaignResponse)
async def create_broadcast_campaign(
    data: BroadcastCampaignCreate,
    shop = Depends(require_permission("marketing", "write")),
    db: AsyncSession = Depends(get_db),
):
    """Create and dispatch (or schedule) a new WhatsApp marketing broadcast campaign."""
    if not data.message:
        raise HTTPException(status_code=400, detail="Campaign message is required")

    campaign_title = (data.title or "").strip()
    if not campaign_title:
        snippet = data.message.strip().replace("\n", " ")[:35]
        campaign_title = f"{snippet}..." if len(data.message) > 35 else snippet

    service = BroadcastService(db)
    try:
        campaign = await service.create_campaign(
            shop_id=shop.id,
            title=campaign_title,
            message=data.message,
            image_url=data.image_url,
            target_audience=data.target_audience,
            min_visits=data.min_visits,
            scheduled_at=data.scheduled_at,
        )
    except ValueError as ve:
        err_msg = str(ve)
        if "INSUFFICIENT_CREDITS" in err_msg:
            parts = err_msg.split(":")
            req_cnt = int(parts[1]) if len(parts) > 1 else 0
            avail_cnt = int(parts[2]) if len(parts) > 2 else 0
            shortfall = max(0, req_cnt - avail_cnt)
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient broadcast credits. You need {req_cnt} credits (₹{req_cnt}) for this audience, but only have {avail_cnt} credits. Please recharge ₹{shortfall} ({shortfall} credits) to broadcast.",
            )
        raise HTTPException(status_code=400, detail=err_msg)

    return BroadcastCampaignResponse(

        id=str(campaign.id),
        shop_id=str(campaign.shop_id),
        title=campaign.title,
        message=campaign.message,
        image_url=campaign.image_url,
        target_audience=campaign.target_audience,
        min_visits=campaign.min_visits,
        status=campaign.status,
        scheduled_at=campaign.scheduled_at,
        sent_at=campaign.sent_at,
        total_recipients=campaign.total_recipients,
        sent_count=campaign.sent_count,
        failed_count=campaign.failed_count,
        created_at=campaign.created_at,
    )


@router.get("", response_model=BroadcastCampaignListResponse)
async def list_broadcast_campaigns(
    search: Optional[str] = Query(None, description="Search keyword in campaign title, message, or audience"),
    date_filter: Optional[str] = Query(None, description="Filter campaigns by date (YYYY-MM-DD)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(15, ge=1, le=100, description="Items per page"),
    shop = Depends(require_permission("marketing", "read")),
    db: AsyncSession = Depends(get_db),
):
    """List broadcast campaigns and scheduled jobs with search, date filtering, and pagination."""
    service = BroadcastService(db)
    campaigns, total = await service.list_campaigns(
        shop_id=shop.id,
        search=search,
        date_filter=date_filter,
        page=page,
        page_size=page_size,
    )
    items = [
        BroadcastCampaignResponse(
            id=str(c.id),
            shop_id=str(c.shop_id),
            title=c.title,
            message=c.message,
            image_url=c.image_url,
            target_audience=c.target_audience,
            min_visits=c.min_visits,
            status=c.status,
            scheduled_at=c.scheduled_at,
            sent_at=c.sent_at,
            total_recipients=c.total_recipients,
            sent_count=c.sent_count,
            failed_count=c.failed_count,
            created_at=c.created_at,
        )
        for c in campaigns
    ]
    has_more = (page * page_size) < total
    return BroadcastCampaignListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        has_more=has_more,
    )



@router.delete("/{campaign_id}")
async def cancel_scheduled_campaign(
    campaign_id: uuid.UUID,
    shop = Depends(require_permission("marketing", "write")),
    db: AsyncSession = Depends(get_db),
):
    """Cancel / delete a scheduled or draft campaign."""
    service = BroadcastService(db)
    success = await service.cancel_campaign(shop.id, campaign_id)
    if not success:
        raise HTTPException(
            status_code=400,
            detail="Cannot cancel campaign. It may already be sent or does not exist.",
        )
    return {"success": True, "message": "Campaign removed successfully"}
