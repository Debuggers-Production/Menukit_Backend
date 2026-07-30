"""Contest API endpoints."""

import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database.session import get_db
from app.database.redis import get_redis
from app.core.deps import get_current_user
from app.models.user import User
from app.models.customer import Customer
from app.core.exceptions import NotFoundException
from app.schemas.contest import (
    ContestCreate, ContestResponse,
    ContestParticipationCreate, ContestParticipationSubmit, ContestParticipationResponse,
    ContestCreditResponse, ContestPayRequest, ContestVerifyRequest, ContestCommentCreate, ContestCommentResponse
)
from app.services.contest_service import ContestService

router = APIRouter(prefix="/contests", tags=["Contests"])


async def _get_customer_by_token(token: str, db: AsyncSession) -> Customer:
    from app.core.security import verify_customer_token
    mobile_number = verify_customer_token(token)
    if not mobile_number:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid customer token"
        )
    result = await db.execute(select(Customer).where(Customer.mobile_number == mobile_number))
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found"
        )
    return customer


def _contest_response(c) -> ContestResponse:
    from sqlalchemy import inspect as sa_inspect
    reserved_count = getattr(c, "total_reserved_participants", 0)
    
    # Safely check if participations relationship is loaded without triggering async lazy loading
    state = sa_inspect(c)
    if "participations" not in state.unloaded:
        if c.participations is not None:
            reserved_count = len(c.participations)

    return ContestResponse(
        id=str(c.id),
        shop_id=str(c.shop_id),
        title=c.title,
        description=c.description,
        reward_type=c.reward_type,
        reward_value=c.reward_value,
        contest_type=c.contest_type,
        applies_to=c.applies_to,
        target_ids=c.target_ids,
        status=c.status,
        ends_at=c.ends_at,
        ranking_criterion=getattr(c, "ranking_criterion", "likes") or "likes",
        min_participants=getattr(c, "min_participants", 1) or 1,
        min_likes=getattr(c, "min_likes", 1) or 1,
        min_comments=getattr(c, "min_comments", 0) or 0,
        min_shares=getattr(c, "min_shares", 0) or 0,
        total_reserved_participants=reserved_count,
        cancel_reason=getattr(c, "cancel_reason", None),
        created_at=c.created_at,
        updated_at=c.updated_at
    )


def _participation_response(p) -> ContestParticipationResponse:
    customer_phone = None
    if getattr(p, "customer", None):
        customer_phone = p.customer.mobile_number
    return ContestParticipationResponse(
        id=str(p.id),
        contest_id=str(p.contest_id),
        customer_id=str(p.customer_id),
        customer_name=getattr(p, "customer_name", None),
        customer_phone=customer_phone,
        content_type=p.content_type,
        text_content=p.text_content,
        media_url=p.media_url,
        likes_count=getattr(p, "likes_count", 0) or 0,
        comments_count=getattr(p, "comments_count", 0) or 0,
        shares_count=getattr(p, "shares_count", 0) or 0,
        time_remaining_seconds=p.time_remaining_seconds,
        is_timer_running=p.is_timer_running,
        timer_last_updated_at=p.timer_last_updated_at,
        is_submitted=p.is_submitted,
        created_at=p.created_at
    )


# VENDOR ENDPOINTS

@router.post("", response_model=ContestResponse)
async def create_contest(
    data: ContestCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Vendor creates a new contest."""
    service = ContestService(db)
    contest = await service.create_contest(user.id, data.model_dump())
    return _contest_response(contest)

@router.post("/{contest_id}/cancel")
async def cancel_contest(
    contest_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Mark a contest as cancelled with reason."""
    from app.models.contest import Contest, ContestParticipation
    result = await db.execute(select(Contest).where(Contest.id == contest_id))
    contest = result.scalar_one_or_none()
    if not contest:
        raise HTTPException(status_code=404, detail="Contest not found")

    # Check if participants already joined
    part_result = await db.execute(select(ContestParticipation).where(ContestParticipation.contest_id == contest_id))
    participations = part_result.scalars().all()
    if len(participations) > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel contest because {len(participations)} participant(s) have reserved entry or joined."
        )
    
    contest.status = "cancelled"
    contest.cancel_reason = "Cancelled by manager"
    await db.commit()
    await db.refresh(contest)
    return _contest_response(contest)

@router.delete("/{contest_id}")
async def delete_contest(
    contest_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Cancel or delete a contest and notify participants of credit refund."""
    from app.models.contest import Contest, ContestParticipation
    result = await db.execute(select(Contest).where(Contest.id == contest_id))
    contest = result.scalar_one_or_none()
    if not contest:
        raise HTTPException(status_code=404, detail="Contest not found")
    
    part_result = await db.execute(select(ContestParticipation).where(ContestParticipation.contest_id == contest_id))
    participations = part_result.scalars().all()
    
    service = ContestService(db)
    if len(participations) > 0:
        await service.cancel_contest_by_merchant(contest_id, reason="Cancelled by manager")
        return {"status": "success", "message": "Contest cancelled, credits refunded and participants notified."}

    # If no participations, hard delete
    await db.delete(contest)
    await db.commit()
    return {"status": "success", "message": "Contest deleted successfully"}

@router.get("/shop/{shop_id}", response_model=List[ContestResponse])
async def get_shop_contests(
    shop_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get all contests for a shop."""
    service = ContestService(db)
    contests = await service.get_contests_by_shop(shop_id)
    return [_contest_response(c) for c in contests]


@router.get("/global-participants-count", response_model=int)
async def get_global_participants_count(
    db: AsyncSession = Depends(get_db)
):
    """Get total joined members count across all contests of all shops."""
    from app.models.contest import ContestParticipation
    from sqlalchemy import func
    result = await db.execute(select(func.count(ContestParticipation.id)))
    return result.scalar() or 0


@router.get("/stats")
async def get_contest_stats(
    db: AsyncSession = Depends(get_db)
):
    """Get total submitted reels/participations and winners count."""
    from app.models.contest import ContestParticipation, Contest
    from sqlalchemy import func
    
    # Total submitted reels/participations count
    reels_result = await db.execute(
        select(func.count(ContestParticipation.id))
        .where(ContestParticipation.is_submitted == True)
    )
    reels_count = reels_result.scalar() or 0

    # Winners count (distinct contests that have ended and have at least 1 submission)
    winners_result = await db.execute(
        select(func.count(func.distinct(ContestParticipation.contest_id)))
        .join(Contest, Contest.id == ContestParticipation.contest_id)
        .where(ContestParticipation.is_submitted == True)
        .where(Contest.status == "ended")
    )
    winners_count = winners_result.scalar() or 0
    
    return {
        "reels_count": reels_count,
        "winners_count": winners_count
    }


@router.get("/all-participations")
async def get_all_participations(
    db: AsyncSession = Depends(get_db)
):
    """Get all submitted participations from all contests of all shops, with contest/shop details."""
    from sqlalchemy.orm import selectinload
    from app.models.contest import ContestParticipation, Contest
    from app.models.shop import Shop
    
    result = await db.execute(
        select(ContestParticipation)
        .where(ContestParticipation.is_submitted == True)
        .options(
            selectinload(ContestParticipation.customer),
            selectinload(ContestParticipation.contest).selectinload(Contest.shop)
        )
        .order_by(ContestParticipation.created_at.desc())
    )
    parts = result.scalars().all()
    
    response_data = []
    for p in parts:
        contest = p.contest
        shop = contest.shop if contest else None
        
        customer_name = "Anonymous"
        if p.customer:
            customer_name = p.customer.name or p.customer.mobile_number or "Anonymous"
            
        response_data.append({
            "id": str(p.id),
            "contest_id": str(p.contest_id) if p.contest_id else None,
            "customer_id": str(p.customer_id) if p.customer_id else None,
            "customer_name": customer_name,
            "content_type": p.content_type,
            "text_content": p.text_content,
            "media_url": p.media_url,
            "likes_count": p.likes_count or 0,
            "comments_count": p.comments_count or 0,
            "time_remaining_seconds": p.time_remaining_seconds or 0,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "contest_title": contest.title if contest else "Untitled Contest",
            "contest_status": contest.status if contest else "ended",
            "shop_name": shop.name if shop else "Unknown Shop",
            "shop_id": str(shop.id) if shop else None,
        })
        
    contest_winner_item = {}
    for item in response_data:
        c_id = item["contest_id"]
        c_status = item["contest_status"]
        if c_status in ("ended", "completed"):
            if c_id not in contest_winner_item:
                contest_winner_item[c_id] = item
            else:
                curr = contest_winner_item[c_id]
                # Tie-breaker key: (likes_count, comments_count, time_remaining_seconds)
                item_score = (item["likes_count"], item["comments_count"], item["time_remaining_seconds"])
                curr_score = (curr["likes_count"], curr["comments_count"], curr["time_remaining_seconds"])
                if item_score > curr_score:
                    contest_winner_item[c_id] = item

    for item in response_data:
        c_id = item["contest_id"]
        c_status = item["contest_status"]
        if c_status in ("ended", "completed") and contest_winner_item.get(c_id) == item:
            item["is_winner"] = True
        else:
            item["is_winner"] = False
            
    return response_data


# CUSTOMER ENDPOINTS

@router.get("/active/shop/{shop_id}", response_model=Optional[ContestResponse])
async def get_active_contest(
    shop_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get active contest for a shop."""
    service = ContestService(db)
    contest = await service.get_active_contest(shop_id)
    if contest:
        return _contest_response(contest)
    return None


@router.post("/pay")
async def buy_credits(
    data: ContestPayRequest,
    db: AsyncSession = Depends(get_db)
):
    """Generates a Cashfree payment link to pay 5 INR for 2 credits."""
    from app.core.config import get_settings
    settings = get_settings()

    CASHFREE_APP_ID = settings.CASHFREE_APP_ID or "TEST107401654fad43cacb2c409c0c8b56104701"
    CASHFREE_SECRET_KEY = settings.CASHFREE_SECRET_KEY or "cfsk_ma_test_f06895ecb53ad98160bac82c1aa110fd_737883de"
    CASHFREE_BASE_URL = "https://sandbox.cashfree.com/pg" if "TEST" in CASHFREE_APP_ID else "https://api.cashfree.com/pg"

    link_id = f"link_{uuid.uuid4().hex[:12]}"
    frontend_url = settings.FRONTEND_URL
    return_url = f"{frontend_url}/shop/{data.shop_id}/contest?payment_success=true&link_id={link_id}&mobile_number={data.mobile_number}"

    headers = {
        "x-client-id": CASHFREE_APP_ID,
        "x-client-secret": CASHFREE_SECRET_KEY,
        "x-api-version": "2023-08-01",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    clean_phone = "".join(filter(str.isdigit, data.mobile_number))
    if len(clean_phone) > 10:
        clean_phone = clean_phone[-10:]

    payload = {
        "link_id": link_id,
        "link_amount": 5.00,
        "link_currency": "INR",
        "customer_details": {
            "customer_phone": clean_phone,
            "customer_id": f"cust_{clean_phone}"
        },
        "link_meta": {
            "return_url": return_url
        },
        "link_purpose": "Contest Credits Entry Fee"
    }

    import httpx
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(f"{CASHFREE_BASE_URL}/links", json=payload, headers=headers)
            if response.status_code != 200:
                raise HTTPException(status_code=400, detail=f"Cashfree failed: {response.text}")
            res_data = response.json()
            return {"link_url": res_data["link_url"], "link_id": link_id}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Cashfree request error: {str(e)}")


@router.post("/pay/verify", response_model=ContestCreditResponse)
async def verify_credits_payment(
    data: ContestVerifyRequest,
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis)
):
    """Verifies the status of a Cashfree payment link and adds credits if PAID."""
    from app.core.config import get_settings
    settings = get_settings()

    CASHFREE_APP_ID = settings.CASHFREE_APP_ID or "TEST107401654fad43cacb2c409c0c8b56104701"
    CASHFREE_SECRET_KEY = settings.CASHFREE_SECRET_KEY or "cfsk_ma_test_f06895ecb53ad98160bac82c1aa110fd_737883de"
    CASHFREE_BASE_URL = "https://sandbox.cashfree.com/pg" if "TEST" in CASHFREE_APP_ID else "https://api.cashfree.com/pg"

    # Clean the input phone number from URL encoding issue (space instead of +)
    mobile = data.mobile_number.strip()
    if " " in mobile:
        mobile = mobile.replace(" ", "+")
    if not mobile.startswith("+"):
        if mobile.startswith("91") and len(mobile) > 10:
            mobile = "+" + mobile
        elif len(mobile) == 10:
            mobile = "+91" + mobile

    cache_key = f"contest_pay_link:{data.link_id}"
    already_processed = await redis.get(cache_key)
    if already_processed:
        from app.models.customer import Customer
        from app.models.contest import ContestCredit
        result = await db.execute(select(Customer).where(Customer.mobile_number == mobile))
        customer = result.scalar_one_or_none()
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")
        credit_result = await db.execute(select(ContestCredit).where(ContestCredit.customer_id == customer.id))
        credit = credit_result.scalar_one_or_none()
        credits_val = credit.credits if credit else 0
        return ContestCreditResponse(customer_id=str(customer.id), credits=credits_val)

    headers = {
        "x-client-id": CASHFREE_APP_ID,
        "x-client-secret": CASHFREE_SECRET_KEY,
        "x-api-version": "2023-08-01",
        "Accept": "application/json"
    }

    import httpx
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{CASHFREE_BASE_URL}/links/{data.link_id}", headers=headers)
            if response.status_code != 200:
                raise HTTPException(status_code=400, detail="Failed to retrieve link status from Cashfree")
            res_data = response.json()
            link_status = res_data.get("link_status")

            if link_status != "PAID":
                raise HTTPException(status_code=400, detail=f"Link has not been paid. Current status: {link_status}")

            service = ContestService(db)
            credit = await service.add_credits(mobile)

            await redis.setex(cache_key, 604800, "processed")

            return ContestCreditResponse(customer_id=str(credit.customer_id), credits=credit.credits)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Verification error: {str(e)}")


@router.get("/credits", response_model=float)
async def get_remaining_credits(
    token: str,
    db: AsyncSession = Depends(get_db)
):
    """Get remaining participation credits for a customer."""
    customer = await _get_customer_by_token(token, db)
    service = ContestService(db)
    return await service.get_credits(customer.id)


@router.post("/{id}/participate", response_model=ContestParticipationResponse)
async def participate_in_contest(
    id: uuid.UUID,
    token: str,
    content_type: str,  # "drawing" | "kavithai"
    db: AsyncSession = Depends(get_db)
):
    """Deduct 1 credit and initiate a 10-minute contest participation session."""
    customer = await _get_customer_by_token(token, db)
    service = ContestService(db)
    try:
        participation = await service.participate_contest(id, customer.id, content_type)
        return _participation_response(participation)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except NotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/participations/{id}/timer", response_model=ContestParticipationResponse)
async def toggle_participation_timer(
    id: uuid.UUID,
    token: str,
    start: bool,  # True to start, False to pause
    db: AsyncSession = Depends(get_db)
):
    """Start or pause the customer's 10-minute participation timer."""
    customer = await _get_customer_by_token(token, db)
    service = ContestService(db)
    try:
        participation = await service.toggle_timer(id, customer.id, start)
        return _participation_response(participation)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except NotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/participations/{id}/submit", response_model=ContestParticipationResponse)
async def submit_contest_entry(
    id: uuid.UUID,
    token: str,
    data: ContestParticipationSubmit,
    db: AsyncSession = Depends(get_db)
):
    """Submit the completed drawing or poetry entry before the timer expires."""
    customer = await _get_customer_by_token(token, db)
    service = ContestService(db)
    try:
        participation = await service.submit_participation(
            id, customer.id, data.text_content, data.media_url
        )
        return _participation_response(participation)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except NotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/participations/{id}/cancel", response_model=bool)
async def cancel_contest_participation(
    id: uuid.UUID,
    token: str,
    db: AsyncSession = Depends(get_db)
):
    """Cancel an unsubmitted participation session and release the reservation."""
    customer = await _get_customer_by_token(token, db)
    service = ContestService(db)
    try:
        return await service.cancel_participation(id, customer.id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except NotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/participations/{id}/like", response_model=bool)
async def toggle_like_participation(
    id: uuid.UUID,
    token: str,
    db: AsyncSession = Depends(get_db)
):
    """Toggle a like on a submission. Returns True if liked, False if unliked."""
    customer = await _get_customer_by_token(token, db)
    service = ContestService(db)
    try:
        liked = await service.like_participation(id, customer.id)
        return liked
    except NotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/{id}/participations", response_model=List[ContestParticipationResponse])
async def get_contest_participations(
    id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get all submitted participations for a contest, ordered by likes."""
    service = ContestService(db)
    participations = await service.get_participations(id)
    return [_participation_response(p) for p in participations]


@router.post("/participations/{id}/comments", response_model=ContestCommentResponse)
async def add_participation_comment(
    id: uuid.UUID,
    token: str,
    data: ContestCommentCreate,
    db: AsyncSession = Depends(get_db)
):
    """Add a comment to a participation."""
    customer = await _get_customer_by_token(token, db)
    service = ContestService(db)
    try:
        comment = await service.add_comment(id, customer.id, data.text)
        return _comment_response(comment)
    except NotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/participations/{id}/comments", response_model=List[ContestCommentResponse])
async def get_participation_comments(
    id: uuid.UUID,
    token: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Get all comments for a participation."""
    customer_id = None
    if token:
        try:
            customer = await _get_customer_by_token(token, db)
            customer_id = customer.id
        except Exception:
            pass
    service = ContestService(db)
    comments = await service.get_comments(id, customer_id)
    return [_comment_response(c) for c in comments]


@router.post("/comments/{comment_id}/like", response_model=bool)
async def toggle_like_comment(
    comment_id: uuid.UUID,
    token: str,
    db: AsyncSession = Depends(get_db)
):
    """Toggle a like on a comment. Returns True if liked, False if unliked."""
    customer = await _get_customer_by_token(token, db)
    service = ContestService(db)
    try:
        liked = await service.like_comment(comment_id, customer.id)
        return liked
    except NotFoundException as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


def _comment_response(c) -> ContestCommentResponse:
    customer_name = None
    if c.customer:
        customer_name = c.customer.name or c.customer.mobile_number
    return ContestCommentResponse(
        id=str(c.id),
        participation_id=str(c.participation_id),
        customer_id=str(c.customer_id),
        customer_name=customer_name,
        text=c.text,
        likes_count=getattr(c, "likes_count", 0),
        is_liked=getattr(c, "is_liked", False),
        created_at=c.created_at
    )
