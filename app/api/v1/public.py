"""Public API endpoints for customer menu access."""

import uuid
from typing import List, Optional
from pydantic import BaseModel

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from fastapi import HTTPException
from sqlalchemy import select, func
from app.models.review import MenuItemReview
from app.schemas.discount import DiscountResponse
from app.schemas.review import ReviewCreate, ReviewResponse, ReviewSummary
from datetime import date, datetime, time
from app.schemas.shop import ShopResponse
from app.schemas.category import CategoryResponse
from app.schemas.menu_item import MenuItemResponse
from app.schemas.common import MessageResponse
from app.services.shop_service import ShopService
from app.services.menu_service import MenuService
from app.services.analytics_service import AnalyticsService
from app.core.exceptions import NotFoundException
from app.api.v1.shops import _shop_to_response
from app.api.v1.categories import _category_response
from app.api.v1.menu_items import _item_response

class PublicCategoryResponse(CategoryResponse):
    """Public category response with menu items."""
    items: List[MenuItemResponse] = []


router = APIRouter(prefix="/public/shop/{shop_id}", tags=["Public Menu"])

shops_router = APIRouter(prefix="/public/shops", tags=["Public Discovery"])


class PublicShopListing(BaseModel):
    """Lightweight shop info for the discovery map."""
    id: str
    name: str
    slug: str
    logo_url: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    opening_time: Optional[str] = None
    closing_time: Optional[str] = None
    active_discounts_count: int = 0
    best_discount_label: Optional[str] = None
    average_rating: Optional[float] = None
    total_reviews: int = 0


@shops_router.get("", response_model=List[PublicShopListing])
async def list_public_shops(
    db: AsyncSession = Depends(get_db),
):
    """List all active shops with discount and rating aggregations for the discovery page."""
    from app.models.shop import Shop
    from app.models.discount import Discount
    from app.models.review import MenuItemReview
    from datetime import datetime, timezone

    # Load all active shops
    result = await db.execute(select(Shop).where(Shop.is_active == True))
    shops = result.scalars().all()

    now = datetime.now(timezone.utc)
    listing = []

    for shop in shops:
        # Count active non-members-only discounts
        disc_result = await db.execute(
            select(Discount).where(
                Discount.shop_id == shop.id,
                Discount.is_active == True,
                Discount.members_only == False,
            )
        )
        all_discounts = disc_result.scalars().all()

        # Filter truly active (within date range)
        active_discs = [
            d for d in all_discounts
            if (d.start_date is None or d.start_date.replace(tzinfo=timezone.utc) <= now)
            and (d.end_date is None or d.end_date.replace(tzinfo=timezone.utc) >= now)
        ]

        # Find best discount label
        best_label = None
        best_value = -1.0
        for d in active_discs:
            if d.discount_type == 'percentage' and d.discount_value is not None:
                v = float(d.discount_value)
                if v > best_value:
                    best_value = v
                    best_label = f"{int(v)}% Off"
            elif d.discount_type == 'flat' and d.discount_value is not None:
                v = float(d.discount_value)
                if v > best_value:
                    best_value = v
                    best_label = f"₹{int(v)} Off"
            elif d.discount_type == 'bogo':
                if best_label is None:
                    best_label = f"Buy {d.buy_quantity} Get {d.get_quantity}"
            elif d.discount_type == 'combo':
                if best_label is None:
                    best_label = "Combo Deal"

        # Average rating from menu_item_reviews
        rating_result = await db.execute(
            select(
                func.avg(MenuItemReview.rating),
                func.count(MenuItemReview.id)
            ).where(MenuItemReview.shop_id == shop.id)
        )
        avg_rating, total_reviews = rating_result.one()
        avg_rating = round(float(avg_rating), 1) if avg_rating else None

        listing.append(PublicShopListing(
            id=str(shop.id),
            name=shop.name,
            slug=shop.slug,
            logo_url=shop.logo_url,
            address=shop.address,
            latitude=shop.latitude,
            longitude=shop.longitude,
            opening_time=shop.opening_time,
            closing_time=shop.closing_time,
            active_discounts_count=len(active_discs),
            best_discount_label=best_label,
            average_rating=avg_rating,
            total_reviews=total_reviews or 0,
        ))

    # Sort: shops with active discounts first, then by rating
    listing.sort(key=lambda s: (-s.active_discounts_count, -(s.average_rating or 0)))
    return listing




class ScanRequest(BaseModel):
    referrer: Optional[str] = None


class ViewRequest(BaseModel):
    item_id: Optional[str] = None
    category_id: Optional[str] = None


class SearchRequest(BaseModel):
    term: str
    result_count: int


@router.get("", response_model=ShopResponse)
async def get_public_shop(
    shop_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get shop details for public menu."""
    service = ShopService(db)
    shop = await service.get_shop_by_id(shop_id)
    if not shop:
        raise NotFoundException("Restaurant not found")
    return _shop_to_response(shop)


@router.get("/menu", response_model=List[PublicCategoryResponse])
async def get_public_menu(
    shop_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get full menu organized by categories."""
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_id(shop_id)
    if not shop:
        raise NotFoundException("Restaurant not found")

    menu_service = MenuService(db)
    categories = await menu_service.get_categories(shop.id)
    
    # Filter out inactive categories
    categories = [cat for cat in categories if cat.is_active]
    
    # We load items for each category. In a real app we might optimize this query
    result = []
    for cat in categories:
        items = await menu_service.get_menu_items(shop.id, category_id=cat.id)
        cat_resp = _category_response(cat)
        # Add items to category dict
        cat_dict = cat_resp.model_dump()
        cat_dict["items"] = [_item_response(i).model_dump() for i in items]
        result.append(cat_dict)
        
    return result


@router.post("/scan", response_model=MessageResponse)
async def record_scan(
    shop_id: uuid.UUID,
    request: Request,
    data: ScanRequest = None,
    db: AsyncSession = Depends(get_db),
):
    """Record a QR scan for analytics."""
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_id(shop_id)
    if not shop:
        raise NotFoundException("Restaurant not found")

    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent", "")[:500]
    ref = data.referrer if data else None

    analytics = AnalyticsService(db)
    await analytics.record_qr_scan(shop.id, ip=ip, ua=ua, ref=ref)
    
    return MessageResponse(message="Scan recorded")


@router.post("/view", response_model=MessageResponse)
async def record_view(
    shop_id: uuid.UUID,
    request: Request,
    data: ViewRequest = None,
    db: AsyncSession = Depends(get_db),
):
    """Record a menu item or category view."""
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_id(shop_id)
    if not shop:
        raise NotFoundException("Restaurant not found")

    ip = request.client.host if request.client else None
    
    item_id = uuid.UUID(data.item_id) if data and data.item_id else None
    cat_id = uuid.UUID(data.category_id) if data and data.category_id else None

    analytics = AnalyticsService(db)
    await analytics.record_menu_view(shop.id, item_id=item_id, category_id=cat_id, ip=ip)
    
    return MessageResponse(message="View recorded")


@router.post("/search", response_model=MessageResponse)
async def record_search(
    shop_id: uuid.UUID,
    data: SearchRequest,
    db: AsyncSession = Depends(get_db),
):
    """Record a search query."""
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_id(shop_id)
    if not shop:
        raise NotFoundException("Restaurant not found")

    analytics = AnalyticsService(db)
    await analytics.record_search(shop.id, data.term, data.result_count)
    
    return MessageResponse(message="Search recorded")


@router.get("/discounts", response_model=List[DiscountResponse])
async def get_active_discounts_public(
    shop_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get active discounts for public display."""
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_id(shop_id)
    if not shop:
        raise NotFoundException("Restaurant not found")

    from app.services.discount_service import DiscountService
    service = DiscountService(db)
    discounts = await service.get_active_discounts(shop.id)

    from app.api.v1.discounts import _discount_response
    return [_discount_response(d) for d in discounts]


# ── Reviews ────────────────────────────────────────────────────────────────────

@router.post("/items/{item_id}/reviews", response_model=ReviewResponse)
async def submit_review(
    shop_id: uuid.UUID,
    item_id: uuid.UUID,
    data: ReviewCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Submit a star review for a menu item (public, no auth required)."""
    # Verify shop exists
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_id(shop_id)
    if not shop:
        raise NotFoundException("Restaurant not found")

    # Verify item belongs to this shop
    menu_service = MenuService(db)
    item = await menu_service.get_menu_item(item_id)
    if not item or item.shop_id != shop.id:
        raise HTTPException(status_code=404, detail="Menu item not found")

    # IP-based spam guard: max 1 review per IP per item ever
    client_ip = request.client.host if request.client else "unknown"
    
    existing = await db.execute(
        select(func.count(MenuItemReview.id)).where(
            MenuItemReview.menu_item_id == item_id,
            MenuItemReview.reviewer_ip == client_ip,
        )
    )
    count_existing = existing.scalar_one()
    if count_existing > 0:
        raise HTTPException(
            status_code=429,
            detail="You have already submitted a review for this item."
        )

    review = MenuItemReview(
        menu_item_id=item_id,
        shop_id=shop.id,
        reviewer_name=data.reviewer_name or None,
        rating=data.rating,
        comment=data.comment,
        reviewer_ip=client_ip,
    )
    db.add(review)
    await db.flush()
    await db.commit()
    await db.refresh(review)

    return ReviewResponse(
        id=str(review.id),
        menu_item_id=str(review.menu_item_id),
        reviewer_name=review.reviewer_name or "Anonymous",
        rating=review.rating,
        comment=review.comment,
        created_at=review.created_at.strftime("%b %d, %Y"),
    )


@router.get("/items/{item_id}/reviews", response_model=ReviewSummary)
async def get_item_reviews_public(
    shop_id: uuid.UUID,
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get reviews summary for a specific menu item (public)."""
    result = await db.execute(
        select(MenuItemReview)
        .where(
            MenuItemReview.menu_item_id == item_id,
            MenuItemReview.shop_id == shop_id,
        )
        .order_by(MenuItemReview.created_at.desc())
        .limit(50)
    )
    reviews = result.scalars().all()

    dist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    total = len(reviews)
    avg = 0.0
    for r in reviews:
        dist[r.rating] = dist.get(r.rating, 0) + 1
        avg += r.rating
    if total:
        avg = round(avg / total, 1)

    return ReviewSummary(
        average_rating=avg,
        total_reviews=total,
        rating_distribution=dist,
        reviews=[
            ReviewResponse(
                id=str(r.id),
                menu_item_id=str(r.menu_item_id),
                reviewer_name=r.reviewer_name or "Anonymous",
                rating=r.rating,
                comment=r.comment,
                created_at=r.created_at.strftime("%b %d, %Y"),
            ) for r in reviews
        ]
    )


@router.get("/items/{item_id}", response_model=MenuItemResponse)
async def get_public_item(
    shop_id: uuid.UUID,
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a single menu item with rating details (public)."""
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_id(shop_id)
    if not shop:
        raise NotFoundException("Restaurant not found")

    menu_service = MenuService(db)
    item = await menu_service.get_menu_item(item_id)
    if not item or item.shop_id != shop.id:
        raise HTTPException(status_code=404, detail="Menu item not found")

    from sqlalchemy import select, func
    from app.models.review import MenuItemReview
    
    result = await db.execute(
        select(
            func.avg(MenuItemReview.rating),
            func.count(MenuItemReview.id)
        ).where(MenuItemReview.menu_item_id == item_id)
    )
    avg_rating, review_count = result.one()
    avg_rating = round(float(avg_rating), 1) if avg_rating else None

    from app.api.v1.menu_items import _item_response
    return _item_response(item, avg_rating=avg_rating, review_count=review_count)
