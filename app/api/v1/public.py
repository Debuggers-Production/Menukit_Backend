"""Public API endpoints for customer menu access."""

import uuid
import asyncio
from typing import List, Optional
from pydantic import BaseModel
from collections import defaultdict

from fastapi import APIRouter, Depends, Request, Header, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db, async_session_factory
from fastapi import HTTPException
from sqlalchemy import select, func
from app.models.review import MenuItemReview
from app.schemas.discount import DiscountResponse
from app.schemas.review import ReviewCreate, ReviewResponse, ReviewSummary
from datetime import datetime, timezone
from app.schemas.shop import ShopResponse
from app.schemas.category import CategoryResponse
from app.schemas.menu_item import MenuItemResponse
from app.schemas.common import MessageResponse
from app.services.shop_service import ShopService
from app.services.menu_service import MenuService
from app.services.analytics_service import AnalyticsService
from app.services.notification_service import NotificationService
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
    category: Optional[str] = None
    cuisine: Optional[str] = None
    city: Optional[str] = None
    area: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    opening_time: Optional[str] = None
    closing_time: Optional[str] = None
    active_discounts_count: int = 0
    best_discount_label: Optional[str] = None
    average_rating: Optional[float] = None
    total_reviews: int = 0
    show_menus_in_discovery: bool = True


@shops_router.get("", response_model=List[PublicShopListing])
async def list_public_shops(
    city: Optional[str] = None,
    category: Optional[str] = None,
    cuisine: Optional[str] = None,
    area: Optional[str] = None,
    open_now: Optional[bool] = None,
    has_offers: Optional[bool] = None,
    min_rating: Optional[float] = None,
    q: Optional[str] = None,
    sort_by: Optional[str] = "nearest",
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """List all active shops for the discovery page with filters and sorting."""
    from app.models.shop import Shop
    from app.models.discount import Discount
    from sqlalchemy.orm import selectinload
    from sqlalchemy import or_

    now = datetime.now(timezone.utc)
    
    # Base query
    stmt = select(Shop).options(selectinload(Shop.settings)).where(Shop.is_active == True)
    
    # Filters
    if city:
        stmt = stmt.where(func.lower(Shop.city) == city.lower())
    if category:
        stmt = stmt.where(func.lower(Shop.category) == category.lower())
    if cuisine:
        stmt = stmt.where(func.lower(Shop.cuisine).contains(cuisine.lower()))
    if area:
        stmt = stmt.where(func.lower(Shop.area) == area.lower())
    if q:
        search_term = f"%{q.lower()}%"
        stmt = stmt.where(or_(
            func.lower(Shop.name).like(search_term),
            func.lower(Shop.category).like(search_term),
            func.lower(Shop.cuisine).like(search_term),
            func.lower(Shop.city).like(search_term),
            func.lower(Shop.area).like(search_term),
        ))
        
    result = await db.execute(stmt)
    shops = result.scalars().all()

    # Filter discoverable
    shops = [s for s in shops if (s.settings.is_discoverable if s.settings else True)]
    if not shops:
        return []

    shop_ids = [s.id for s in shops]

    # Discounts
    disc_result = await db.execute(
        select(Discount).where(
            Discount.shop_id.in_(shop_ids),
            Discount.is_active == True,
            Discount.visibility_type != 'members_only',
        )
    )
    all_discounts = disc_result.scalars().all()
    discount_map = defaultdict(list)
    for d in all_discounts:
        in_range = (
            (d.start_date is None or d.start_date.replace(tzinfo=timezone.utc) <= now)
            and (d.end_date is None or d.end_date.replace(tzinfo=timezone.utc) >= now)
        )
        if in_range:
            discount_map[d.shop_id].append(d)

    # Ratings
    rating_result = await db.execute(
        select(
            MenuItemReview.shop_id,
            func.avg(MenuItemReview.rating).label("avg_rating"),
            func.count(MenuItemReview.id).label("total_reviews"),
        )
        .where(MenuItemReview.shop_id.in_(shop_ids))
        .group_by(MenuItemReview.shop_id)
    )
    rating_map = {row.shop_id: (row.avg_rating, row.total_reviews) for row in rating_result}

    listing = []
    import math
    for shop in shops:
        show_menus = shop.settings.show_menus_in_discovery if shop.settings else True
        active_discs = discount_map.get(shop.id, [])
        if has_offers and not active_discs:
            continue
            
        avg_rating_raw, total_reviews = rating_map.get(shop.id, (None, 0))
        avg_rating = round(float(avg_rating_raw), 1) if avg_rating_raw else None
        
        if min_rating and (avg_rating is None or avg_rating < min_rating):
            continue

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

        listing.append(PublicShopListing(
            id=str(shop.id),
            name=shop.name,
            slug=shop.slug,
            logo_url=shop.logo_url,
            address=shop.address,
            category=shop.category,
            cuisine=shop.cuisine,
            city=shop.city,
            area=shop.area,
            latitude=shop.latitude,
            longitude=shop.longitude,
            opening_time=shop.opening_time,
            closing_time=shop.closing_time,
            active_discounts_count=len(active_discs),
            best_discount_label=best_label,
            average_rating=avg_rating,
            total_reviews=total_reviews or 0,
            show_menus_in_discovery=show_menus,
        ))

    # Calculate distance if lat/lng provided
    if lat is not None and lng is not None:
        def calc_dist(s):
            if s.latitude is None or s.longitude is None:
                return float('inf')
            # very simple pythagorean distance for sorting, not actual km
            return math.hypot(s.latitude - lat, s.longitude - lng)
        for s in listing:
            s.__dict__['_dist'] = calc_dist(s)
            
    # Sorting
    if sort_by == "nearest" and lat is not None and lng is not None:
        listing.sort(key=lambda s: s.__dict__.get('_dist', float('inf')))
    elif sort_by == "popular":
        listing.sort(key=lambda s: (-s.total_reviews, -(s.average_rating or 0)))
    elif sort_by == "rating":
        listing.sort(key=lambda s: -(s.average_rating or 0))
    elif sort_by == "a-z":
        listing.sort(key=lambda s: s.name.lower())
    else: # default sorting from original
        listing.sort(key=lambda s: (-s.active_discounts_count, -(s.average_rating or 0)))

    # Pagination
    return listing[offset : offset + limit]


# ── Request models ─────────────────────────────────────────────────────────────

class ScanRequest(BaseModel):
    referrer: Optional[str] = None


class ViewRequest(BaseModel):
    item_id: Optional[str] = None
    category_id: Optional[str] = None


class SearchRequest(BaseModel):
    term: str
    result_count: int


# ── Shop & Menu endpoints ──────────────────────────────────────────────────────

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
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """Get full menu organized by categories.

    Optimized: 2 queries total instead of N+1 (one per category).
    """
    from app.models.category import Category
    from app.models.menu_item import MenuItem
    from sqlalchemy.orm import selectinload

    # ── 1. Verify shop exists ─────────────────────────────────────────────────
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_id(shop_id)
    if not shop:
        raise NotFoundException("Restaurant not found")

    # ── 2. Load all active categories ────────────────────────────────────────
    cat_result = await db.execute(
        select(Category)
        .where(Category.shop_id == shop_id, Category.is_active == True)
        .order_by(Category.display_order)
        .offset(offset)
        .limit(limit)
    )
    categories = cat_result.scalars().all()
    if not categories:
        return []

    cat_ids = [c.id for c in categories]

    # ── 3. Single bulk query for ALL items across all categories ─────────────
    items_result = await db.execute(
        select(MenuItem)
        .options(selectinload(MenuItem.images))
        .where(
            MenuItem.shop_id == shop_id,
            MenuItem.category_id.in_(cat_ids),
            MenuItem.is_available == True,
        )
        .order_by(MenuItem.category_id, MenuItem.display_order)
    )
    all_items = items_result.scalars().all()

    # Group items by category in Python
    items_by_cat: dict = defaultdict(list)
    for item in all_items:
        items_by_cat[item.category_id].append(item)

    # ── 4. Assemble response ──────────────────────────────────────────────────
    result = []
    for cat in categories:
        cat_resp = _category_response(cat)
        cat_dict = cat_resp.model_dump()
        cat_dict["items"] = [_item_response(i).model_dump() for i in items_by_cat.get(cat.id, [])]
        result.append(cat_dict)

    return result


# ── Analytics endpoints (fire-and-forget) ─────────────────────────────────────

@router.post("/scan", response_model=MessageResponse)
async def record_scan(
    shop_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    data: ScanRequest = None,
    db: AsyncSession = Depends(get_db),
):
    """Record a QR scan — writes analytics in background."""
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_id(shop_id)
    if not shop:
        raise NotFoundException("Restaurant not found")

    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent", "")[:500]
    ref = data.referrer if data else None

    async def _record():
        try:
            async with async_session_factory() as bg_db:
                await AnalyticsService(bg_db).record_qr_scan(shop.id, ip=ip, ua=ua, ref=ref)
        except Exception:
            pass

    background_tasks.add_task(_record)
    return MessageResponse(message="Scan recorded")


@router.post("/view", response_model=MessageResponse)
async def record_view(
    shop_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    data: ViewRequest = None,
    db: AsyncSession = Depends(get_db),
):
    """Record a menu view — writes analytics in background."""
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_id(shop_id)
    if not shop:
        raise NotFoundException("Restaurant not found")

    ip = request.client.host if request.client else None
    item_id = uuid.UUID(data.item_id) if data and data.item_id else None
    cat_id = uuid.UUID(data.category_id) if data and data.category_id else None

    async def _record():
        try:
            async with async_session_factory() as bg_db:
                await AnalyticsService(bg_db).record_menu_view(shop.id, item_id=item_id, category_id=cat_id, ip=ip)
        except Exception:
            pass

    background_tasks.add_task(_record)
    return MessageResponse(message="View recorded")


@router.post("/search", response_model=MessageResponse)
async def record_search(
    shop_id: uuid.UUID,
    data: SearchRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Record a search query — writes analytics in background."""
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_id(shop_id)
    if not shop:
        raise NotFoundException("Restaurant not found")

    async def _record():
        try:
            async with async_session_factory() as bg_db:
                await AnalyticsService(bg_db).record_search(shop.id, data.term, data.result_count)
        except Exception:
            pass

    background_tasks.add_task(_record)
    return MessageResponse(message="Search recorded")


# ── Discounts ──────────────────────────────────────────────────────────────────

@router.get("/discounts", response_model=List[DiscountResponse])
async def get_active_discounts_public(
    shop_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    Authorization: Optional[str] = Header(None)
):
    """Get active discounts for public display, filtering out hidden ones if unauthenticated."""
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_id(shop_id)
    if not shop:
        raise NotFoundException("Restaurant not found")

    from app.services.discount_service import DiscountService
    service = DiscountService(db)
    discounts = await service.get_active_discounts(shop.id)

    is_authenticated = False
    if Authorization:
        from app.core.security import verify_customer_token
        token = Authorization.replace("Bearer ", "") if "Bearer " in Authorization else Authorization
        if verify_customer_token(token):
            is_authenticated = True

    from app.api.v1.discounts import _discount_response

    result = []
    for d in discounts:
        if not is_authenticated and d.visibility_type == 'members_only_hidden':
            continue
        result.append(_discount_response(d))

    return result[offset : offset + limit]


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
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_id(shop_id)
    if not shop:
        raise NotFoundException("Restaurant not found")

    menu_service = MenuService(db)
    item = await menu_service.get_menu_item(item_id)
    if not item or item.shop_id != shop.id:
        raise HTTPException(status_code=404, detail="Menu item not found")

    client_ip = request.client.host if request.client else "unknown"

    existing = await db.execute(
        select(func.count(MenuItemReview.id)).where(
            MenuItemReview.menu_item_id == item_id,
            MenuItemReview.reviewer_ip == client_ip,
        )
    )
    if existing.scalar_one() > 0:
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

    # Send Notification
    await NotificationService(db).create_notification(
        shop_id=shop.id,
        type="NEW_REVIEW",
        title="New Food Review!",
        message=f"Someone left a {data.rating}-star review for {item.name}.",
        metadata={"item_id": str(item.id), "review_id": str(review.id)}
    )

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

    result = await db.execute(
        select(
            func.avg(MenuItemReview.rating),
            func.count(MenuItemReview.id)
        ).where(MenuItemReview.menu_item_id == item_id)
    )
    avg_rating, review_count = result.one()
    avg_rating = round(float(avg_rating), 1) if avg_rating else None

    return _item_response(item, avg_rating=avg_rating, review_count=review_count)

@shops_router.get("/by-slug/{slug}", response_model=ShopResponse)
async def get_shop_by_slug(
    slug: str,
    db: AsyncSession = Depends(get_db),
):
    """Get shop details by slug for public SEO page."""
    from app.models.shop import Shop
    from sqlalchemy.orm import selectinload
    
    result = await db.execute(
        select(Shop)
        .options(
            selectinload(Shop.settings),
            selectinload(Shop.theme)
        )
        .where(Shop.slug == slug, Shop.is_active == True)
    )
    shop = result.scalars().first()
    
    if not shop:
        raise NotFoundException("Restaurant not found")
        
    return _shop_to_response(shop)
