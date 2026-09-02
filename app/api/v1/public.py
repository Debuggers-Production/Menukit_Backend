"""Public API endpoints for customer menu access."""

import uuid
import asyncio
from typing import List, Optional
from pydantic import BaseModel
from collections import defaultdict

from fastapi import APIRouter, Depends, Request, Header, BackgroundTasks, WebSocket, WebSocketDisconnect,Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db, async_session_factory
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from app.models.review import MenuItemReview
from app.schemas.discount import DiscountResponse
from app.schemas.review import ReviewCreate, ReviewResponse, ReviewSummary
from datetime import datetime, timezone
from app.schemas.shop import ShopResponse
from app.schemas.category import CategoryResponse
from app.schemas.menu_item import MenuItemResponse
from app.schemas.common import MessageResponse
from app.schemas.qr_code import QRCodeResponse
from app.schemas.order import OrderCreate, OrderResponse
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
    catalog_ids = [s.menu_catalog_id for s in shops if s.menu_catalog_id]
    shop_to_catalog = {s.id: s.menu_catalog_id for s in shops if s.menu_catalog_id}
    catalog_to_shop = {s.menu_catalog_id: s.id for s in shops if s.menu_catalog_id}

    # Discounts
    disc_result = await db.execute(
        select(Discount).where(
            Discount.menu_catalog_id.in_(catalog_ids),
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
            # Map back to shop_id for response grouping
            shop_id_for_disc = catalog_to_shop.get(d.menu_catalog_id)
            if shop_id_for_disc:
                discount_map[shop_id_for_disc].append(d)

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
    """Get shop details for public menu with subscription enforcement (Cached)."""
    import json
    from app.database.redis import get_redis
    r_client = await get_redis()
    cache_key = f"public:shop:{str(shop_id)}"
    
    try:
        cached_data = await r_client.get(cache_key)
        if cached_data:
            return json.loads(cached_data)
    except Exception:
        pass

    service = ShopService(db)
    shop = await service.get_shop_by_id(shop_id)
    if not shop:
        raise NotFoundException("Restaurant not found")
    from app.api.v1.shops import format_shop_response_with_subscription_checks
    resp = await format_shop_response_with_subscription_checks(shop, db)
    
    try:
        # Convert pydantic response model to dict/json for redis cache
        data_dict = resp.model_dump() if hasattr(resp, "model_dump") else resp
        await r_client.setex(cache_key, 300, json.dumps(data_dict, default=str))
    except Exception:
        pass
        
    return resp

@router.get("/categories", response_model=List[PublicCategoryResponse])
async def get_public_categories(
    shop_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """Get ONLY active categories for a shop (no items)."""
    import json
    from app.database.redis import get_redis
    r_client = await get_redis()
    cache_key = f"public:categories:{str(shop_id)}:{limit}:{offset}"
    
    try:
        cached_cats = await r_client.get(cache_key)
        if cached_cats:
            return json.loads(cached_cats)
    except Exception:
        pass

    from app.models.category import Category
    
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_id(shop_id)
    if not shop:
        raise NotFoundException("Restaurant not found")

    catalog_id = shop.menu_catalog_id
    if not catalog_id:
        return []

    cat_result = await db.execute(
        select(Category)
        .where(Category.menu_catalog_id == catalog_id, Category.is_active == True)
        .order_by(Category.display_order)
        .offset(offset)
        .limit(limit)
    )
    categories = cat_result.scalars().all()
    if not categories:
        return []

    result = []
    for cat in categories:
        cat_resp = _category_response(cat)
        cat_dict = cat_resp.model_dump()
        cat_dict["items"] = []  # Explicitly empty
        result.append(cat_dict)

    try:
        await r_client.setex(cache_key, 300, json.dumps(result, default=str))
    except Exception:
        pass

    return result

@router.get("/items", response_model=List[MenuItemResponse])
async def get_public_items(
    shop_id: uuid.UUID,
    category_id: Optional[uuid.UUID] = None,
    discount_id: Optional[uuid.UUID] = None,
    search: Optional[str] = None,
    food_type: Optional[str] = None,
    status: Optional[str] = None,
    sort_by: Optional[str] = None,
    include_unavailable: bool = False,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """Get items for a shop with filtering, discount applicability, and sorting options."""
    from app.models.menu_item import MenuItem
    from sqlalchemy.orm import selectinload
    
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_id(shop_id)
    if not shop:
        raise NotFoundException("Restaurant not found")

    catalog_id = shop.menu_catalog_id
    if not catalog_id:
        return []

    query = (
        select(MenuItem)
        .options(selectinload(MenuItem.images))
        .where(MenuItem.menu_catalog_id == catalog_id)
    )

    if not include_unavailable:
        query = query.where(MenuItem.is_available == True)

    if category_id:
        query = query.where(MenuItem.category_id == category_id)

    if discount_id:
        from app.models.discount import Discount
        disc_res = await db.execute(select(Discount).where(Discount.id == discount_id, Discount.is_active == True))
        disc = disc_res.scalar_one_or_none()
        if disc:
            if disc.applies_to == "category" and disc.target_ids:
                cat_uuids = [uuid.UUID(str(tid)) for tid in disc.target_ids if tid]
                query = query.where(MenuItem.category_id.in_(cat_uuids))
            elif disc.applies_to == "items" and disc.target_ids:
                item_uuids = [uuid.UUID(str(tid)) for tid in disc.target_ids if tid]
                query = query.where(MenuItem.id.in_(item_uuids))
    
    if search:
        query = query.where(func.lower(MenuItem.name).contains(search.lower()))

    if food_type and food_type != 'all':
        # Handles food_types JSON/Array containment matching (e.g. veg, non-veg, drink, dessert)
        query = query.where(MenuItem.food_types.contains([food_type]))

    if status:
        if status == 'available' or status == 'in_stock':
            query = query.where(MenuItem.is_available == True)
        elif status == 'not_available' or status == 'out_of_stock':
            query = query.where(MenuItem.is_available == False)
        elif status == 'bestseller':
            query = query.where(MenuItem.is_bestseller == True)
        elif status == 'chef_special':
            query = query.where(MenuItem.is_highlighted == True)

    # Sorting
    if sort_by == 'price_asc':
        query = query.order_by(MenuItem.price.asc(), MenuItem.display_order.asc())
    elif sort_by == 'price_desc':
        query = query.order_by(MenuItem.price.desc(), MenuItem.display_order.asc())
    else:
        query = query.order_by(MenuItem.category_id, MenuItem.display_order)

    query = query.offset(offset).limit(limit)
    
    items_result = await db.execute(query)
    all_items = items_result.scalars().all()
    
    result = [_item_response(i) for i in all_items]
    return result

@router.get("/menu", response_model=List[PublicCategoryResponse])
async def get_public_menu(
    shop_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """Get full menu organized by categories (Cached).

    Optimized: Served directly from Redis cache if present.
    """
    import json
    from app.database.redis import get_redis
    r_client = await get_redis()
    cache_key = f"public:menu:{str(shop_id)}:{limit}:{offset}"
    
    try:
        cached_menu = await r_client.get(cache_key)
        if cached_menu:
            return json.loads(cached_menu)
    except Exception:
        pass

    from app.models.category import Category
    from app.models.menu_item import MenuItem
    from sqlalchemy.orm import selectinload

    # ── 1. Verify shop exists ─────────────────────────────────────────────────
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_id(shop_id)
    if not shop:
        raise NotFoundException("Restaurant not found")

    catalog_id = shop.menu_catalog_id
    if not catalog_id:
        return []

    # ── 2. Load all active categories ────────────────────────────────────────
    cat_result = await db.execute(
        select(Category)
        .where(Category.menu_catalog_id == catalog_id, Category.is_active == True)
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
            MenuItem.menu_catalog_id == catalog_id,
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

    try:
        await r_client.setex(cache_key, 300, json.dumps(result, default=str))
    except Exception:
        pass

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
                await bg_db.commit()
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
                await bg_db.commit()
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
                await bg_db.commit()
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
    if not item or item.menu_catalog_id != shop.menu_catalog_id:
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
    if not item or item.menu_catalog_id != shop.menu_catalog_id:
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


@router.get("/qr", response_model=QRCodeResponse)
async def get_public_shop_qr(
    shop_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get public QR code style details for a shop. Automatically generates a default one if not found."""
    from app.models.qr_code import QRCode
    from app.models.shop import Shop
    
    # Verify the shop exists
    shop_res = await db.execute(select(Shop).where(Shop.id == shop_id))
    shop = shop_res.scalar_one_or_none()
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    result = await db.execute(
        select(QRCode).where(QRCode.user_id == shop.user_id)
    )
    qr = result.scalar_one_or_none()
    
    if not qr:
        from app.core.config import get_settings
        settings = get_settings()
        
        qr_url = f"{settings.FRONTEND_URL}/shop/{shop.id}?type=qr"
        
        qr = QRCode(
            user_id=shop.user_id,
            qr_url=qr_url,
            qr_image_url=None,
            qr_svg_data=None,
        )
        db.add(qr)
        await db.commit()
        await db.refresh(qr)
        
    return QRCodeResponse.model_validate(qr)


@router.post("/orders", response_model=OrderResponse)
async def create_public_order(
    shop_id: uuid.UUID,
    order_data: OrderCreate,
    db: AsyncSession = Depends(get_db),
):
    """Place a dine-in, takeaway, or delivery order with subscription feature checks."""
    from app.services.subscription_helper import get_shop_subscription_permissions
    perms = await get_shop_subscription_permissions(shop_id, db)
    
    if (order_data.order_type in ["takeaway", "delivery"] or order_data.payment_method != "cash") and not perms["online_orders"]:
        raise HTTPException(
            status_code=403,
            detail="Online ordering (Takeaway & Delivery) is disabled for this shop due to an inactive or expired subscription."
        )

    from app.services.order_service import OrderService
    service = OrderService(db)
    order = await service.create_order(shop_id, order_data)
    await db.commit()
    return OrderResponse.model_validate(order)


@router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_public_order(
    shop_id: uuid.UUID,
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get status tracking of an order."""
    from app.services.order_service import OrderService
    service = OrderService(db)
    order = await service.get_order_by_id(order_id)
    if order.shop_id != shop_id:
        raise HTTPException(status_code=404, detail="Order not found")
    return OrderResponse.model_validate(order)


@router.post("/orders/{order_id}/pay")
async def pay_public_order(
    shop_id: uuid.UUID,
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a Razorpay order for the given order.
    Fee breakdown:
      - 1% Platform Fee (Menukit)
      - 3% Payment Gateway Fee
      - 18% GST on Payment Gateway Fee
    Returns full breakdown + Razorpay key + order id.
    """
    from app.core.config import get_settings
    from app.models.order import Order
    from app.models.shop_settings import ShopSettings

    settings = get_settings()

    result = await db.execute(
        select(Order).where(Order.id == order_id, Order.shop_id == shop_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    settings_result = await db.execute(select(ShopSettings).where(ShopSettings.shop_id == shop_id))
    shop_settings = settings_result.scalar_one_or_none()

    if order.payment_status == "paid":
        raise HTTPException(status_code=400, detail="Order has already been paid")

    # Map currency symbol or code to standard 3-letter ISO code
    CURRENCY_MAP = {
        "₹": "INR", "INR": "INR",
        "$": "USD", "USD": "USD",
        "€": "EUR", "EUR": "EUR",
        "£": "GBP", "GBP": "GBP",
        "¥": "JPY", "JPY": "JPY",
        "AED": "AED",
        "SAR": "SAR",
        "A$": "AUD", "AUD": "AUD",
        "C$": "CAD", "CAD": "CAD",
        "S$": "SGD", "SGD": "SGD",
        "RM": "MYR", "MYR": "MYR",
    }
    raw_curr = (shop_settings.currency if shop_settings and shop_settings.currency else "₹").strip()
    target_currency = CURRENCY_MAP.get(raw_curr, "INR")
    curr_symbol = raw_curr if raw_curr in ["₹", "$", "€", "£", "¥", "A$", "C$", "S$", "AED", "SAR", "RM"] else target_currency

    base_total = float(order.total_amount)
    platform_fee = round(base_total * 0.02, 2)
    pg_fee = round(base_total * 0.03, 2)
    gst_on_fee = round(pg_fee * 0.18, 2)
    grand_total = round(base_total + platform_fee + pg_fee + gst_on_fee, 2)

    is_zero_decimal = target_currency in ["JPY", "KRW", "VND", "CLP"]
    amount_subunits = int(round(grand_total)) if is_zero_decimal else int(round(grand_total * 100))

    # Mock mode
    if settings.MOCK_PAYMENT_MODE:
        mock_order_id = f"order_mock_{order_id.hex[:12]}"
        order.razorpay_order_id = mock_order_id
        await db.commit()
        return {
            "razorpay_order_id": mock_order_id,
            "razorpay_key": settings.RAZORPAY_KEY_ID or "rzp_test_mock",
            "base_total": base_total,
            "platform_fee": platform_fee,
            "pg_fee": pg_fee,
            "gst_on_fee": gst_on_fee,
            "grand_total": grand_total,
            "amount": amount_subunits,
            "currency": target_currency,
            "currency_symbol": curr_symbol,
            "mock_mode": True,
        }

    try:
        import razorpay
        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        order_data = {
            "amount": amount_subunits,
            "currency": target_currency,
            "receipt": f"order_{str(order_id)[:8]}_{int(datetime.now(timezone.utc).timestamp())}",
            "notes": {
                "order_id": str(order_id),
                "shop_id": str(shop_id),
                "currency": target_currency,
                "base_total": f"{curr_symbol}{base_total:.2f}",
                "platform_fee": f"{curr_symbol}{platform_fee:.2f}",
                "pg_fee": f"{curr_symbol}{pg_fee:.2f}",
                "gst_on_fee": f"{curr_symbol}{gst_on_fee:.2f}",
            }
        }
        
        if shop_settings and shop_settings.razorpay_account_id:
            # Transfer 100% of vendor base amount directly to their Razorpay account
            vendor_net_amount = base_total
            vendor_amount_subunits = int(round(vendor_net_amount)) if is_zero_decimal else int(round(vendor_net_amount * 100))
            order_data["transfers"] = [
                {
                    "account": shop_settings.razorpay_account_id,
                    "amount": vendor_amount_subunits,
                    "currency": target_currency,
                    "notes": {
                        "type": "vendor_payout",
                        "order_id": str(order_id)
                    },
                    "on_hold": 0
                }
            ]

        try:
            rzp_order = client.order.create(data=order_data)
        except Exception as rzp_e:
            print(f"DEBUG: Razorpay order creation with transfers failed: {rzp_e}")
            if "transfers" in order_data:
                print("DEBUG: Retrying order creation WITHOUT transfers array. Platform owner will need to settle this manually until sub-account is activated.")
                del order_data["transfers"]
                rzp_order = client.order.create(data=order_data)
            else:
                raise rzp_e

        order.razorpay_order_id = rzp_order["id"]
        await db.commit()

        return {
            "razorpay_order_id": rzp_order["id"],
            "razorpay_key": settings.RAZORPAY_KEY_ID,
            "base_total": base_total,
            "platform_fee": platform_fee,
            "pg_fee": pg_fee,
            "gst_on_fee": gst_on_fee,
            "grand_total": grand_total,
            "amount": rzp_order["amount"],
            "currency": rzp_order["currency"],
            "currency_symbol": curr_symbol,
            "mock_mode": False,
        }
    except Exception as e:
        print(f"Razorpay order creation error: {e}")
        raise HTTPException(status_code=500, detail=f"Payment gateway error: {str(e)}")


@router.post("/orders/{order_id}/verify", response_model=OrderResponse)
async def verify_public_order_payment(
    shop_id: uuid.UUID,
    order_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Verify Razorpay payment signature and mark order as paid.
    Accepts JSON body: { razorpay_order_id, razorpay_payment_id, razorpay_signature }
    """
    from app.core.config import get_settings
    from app.models.order import Order

    settings = get_settings()
    try:
        body = await request.json()
    except Exception:
        body = {}

    razorpay_order_id = body.get("razorpay_order_id", "")
    razorpay_payment_id = body.get("razorpay_payment_id", "")
    razorpay_signature = body.get("razorpay_signature", "")

    result = await db.execute(
        select(Order).where(Order.id == order_id, Order.shop_id == shop_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.payment_status == "paid":
        return OrderResponse.model_validate(order)

    # Mock / test mode — accept any payment ID starting with mock prefix
    is_valid = False
    if settings.MOCK_PAYMENT_MODE and (
        razorpay_order_id.startswith("order_mock_") or 
        razorpay_payment_id.startswith("pay_mock_")
    ):
        is_valid = True
    else:
        try:
            import razorpay
            client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
            params_dict = {
                'razorpay_order_id': razorpay_order_id,
                'razorpay_payment_id': razorpay_payment_id,
                'razorpay_signature': razorpay_signature
            }
            client.utility.verify_payment_signature(params_dict)
            is_valid = True
        except Exception as e:
            print(f"Razorpay signature verification error: {e}")
            is_valid = False

    if not is_valid:
        raise HTTPException(status_code=400, detail="Payment verification failed. Invalid signature.")

    # Optimistic Concurrency Control Check
    if order.order_status == "CANCELLED":
        # The order was cancelled (likely by the payment timeout background job).
        # We must trigger an automatic refund!
        if not settings.MOCK_PAYMENT_MODE:
            try:
                import razorpay
                client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
                client.payment.refund(razorpay_payment_id, {
                    "amount": int(order.total_amount * 100)
                })
                print(f"Auto-refunded {razorpay_payment_id} because order {order.id} was already cancelled.")
            except Exception as e:
                print(f"Failed to auto-refund cancelled order {order.id}: {e}")
        
        # We still return the response so the frontend knows, but it's fundamentally cancelled
        order.payment_status = "refunded"
        order.payment_session_id = razorpay_payment_id
        await db.commit()
        return OrderResponse.model_validate(order)

    # If it wasn't cancelled, calculate exact paid amount (including convenience/gateway fees) and mark as PAID!
    base_total = float(order.total_amount)
    platform_fee = round(base_total * 0.02, 2)
    pg_fee = round(base_total * 0.03, 2)
    gst_on_fee = round(pg_fee * 0.18, 2)
    paid_total = round(base_total + platform_fee + pg_fee + gst_on_fee, 2)

    # Try fetching exact paid amount from Razorpay if available
    if not settings.MOCK_PAYMENT_MODE and razorpay_payment_id:
        try:
            import razorpay
            client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
            pay_obj = client.payment.fetch(razorpay_payment_id)
            if pay_obj and "amount" in pay_obj:
                paid_total = round(float(pay_obj["amount"]) / 100.0, 2)
        except Exception as p_err:
            print(f"Could not fetch razorpay payment amount: {p_err}")

    from sqlalchemy import update
    update_stmt = (
        update(Order)
        .where(Order.id == order.id, Order.version == order.version)
        .values(
            payment_status="paid",
            payment_method="online",
            order_status="PAID",
            total_amount=paid_total,
            razorpay_order_id=razorpay_order_id,
            payment_session_id=razorpay_payment_id,
            version=Order.version + 1
        )
    )

    res = await db.execute(update_stmt)
    if res.rowcount == 0:
        # OCC Failure! State changed while we were verifying.
        # Could just throw a 409 Conflict so the frontend retries.
        await db.rollback()
        raise HTTPException(status_code=409, detail="Order state changed during verification. Please try again.")

    # Refresh order object
    await db.refresh(order)

    # Award 0.15 Contest Credits if order total >= ₹100
    from app.services.order_service import OrderService
    order_service = OrderService(db)
    await order_service._award_contest_credits_if_eligible(order)

    # Create notification for merchant now that payment is confirmed
    from app.services.notification_service import NotificationService
    notif_service = NotificationService(db)
    await notif_service.create_notification(
        shop_id=shop_id,
        type="NEW_ORDER",
        title="New Paid Order Received",
        message=f"New paid order #{order.id.hex[:8]} placed by {order.customer_name} ({order.order_type})",
        metadata={"order_id": str(order.id)}
    )

    # Broadcast websocket event to merchant dashboard
    from app.services.websocket_manager import manager, customer_manager
    from app.services.order_service import get_customer_user_id
    
    ws_msg = {
        "event": "NEW_ORDER",
        "type": "NEW_ORDER",
        "data": OrderResponse.model_validate(order).model_dump(mode="json"),
        "title": "New Paid Order Received",
        "message": f"New paid order #{order.id.hex[:8]} placed by {order.customer_name} ({order.order_type})"
    }
    await manager.broadcast_to_shop(str(shop_id), ws_msg)
    
    # Broadcast to customer websocket
    cust_msg = {
        "type": "order_update",
        "order_id": str(order.id),
        "status": order.order_status,
        "payment_status": order.payment_status,
        "customer_phone": order.customer_phone,
    }
    clean_phone = "".join(filter(str.isdigit, order.customer_phone))
    customer_ws_id = get_customer_user_id(clean_phone)
    await customer_manager.broadcast_to_customer(customer_ws_id, cust_msg)

    # Send WhatsApp template notification 'menukit_order_create'
    await order_service._send_order_status_whatsapp_notification(order)

    await db.commit()
    await db.refresh(order)
    return OrderResponse.model_validate(order)



@router.post("/orders/{order_id}/cancel")
async def cancel_unpaid_public_order(
    shop_id: uuid.UUID,
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Cancel unpaid order when customer dismisses payment screen or payment fails."""
    from app.models.order import Order
    result = await db.execute(
        select(Order).where(Order.id == order_id, Order.shop_id == shop_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.payment_status != "paid":
        order.order_status = "cancelled"
        order.payment_status = "cancelled"
        await db.commit()

    return {"status": "success", "message": "Order cancelled"}


def _get_phone_variants(phone: Optional[str]) -> list[str]:
    if not phone:
        return []
    raw = phone.strip()
    clean = "".join(filter(str.isdigit, raw))
    if not clean:
        return [raw] if raw else []
    variants = {raw, clean}
    if len(clean) == 10:
        variants.add(f"+91{clean}")
        variants.add(f"91{clean}")
    elif len(clean) == 12 and clean.startswith("91"):
        variants.add(clean[2:])
        variants.add(f"+{clean}")
    elif len(clean) > 10:
        variants.add(clean[-10:])
        variants.add(f"+91{clean[-10:]}")
        variants.add(f"91{clean[-10:]}")
    return list(variants)


@router.get("/my-orders", response_model=List[OrderResponse])
async def get_my_orders(
    shop_id: uuid.UUID,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Get all past orders placed by the customer in this shop using their customer token."""
    from app.core.security import verify_customer_token
    mobile_number = verify_customer_token(token)
    if not mobile_number:
        raise HTTPException(status_code=401, detail="Invalid customer token")
        
    from app.models.order import Order
    from sqlalchemy import select, not_, and_
    from sqlalchemy.orm import selectinload
    
    mobile_variants = _get_phone_variants(mobile_number)
    result = await db.execute(
        select(Order)
        .options(selectinload(Order.items))
        .where(
            Order.shop_id == shop_id,
            Order.customer_phone.in_(mobile_variants)
        )
        .order_by(Order.created_at.desc())
    )
    orders = result.scalars().all()
    return [OrderResponse.model_validate(o) for o in orders]


@router.websocket("/ws/customer/{customer_id}")
async def customer_websocket_endpoint(websocket: WebSocket, customer_id: str):
    """Connect a customer to their live order updates stream using secure customer user ID."""
    from app.services.websocket_manager import customer_manager
    await customer_manager.connect(customer_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        customer_manager.disconnect(customer_id, websocket)


# -------------------------------------------------------------
# INDIVIDUAL LIGHTWEIGHT CUSTOMER PROFILE & TAB ENDPOINTS
# -------------------------------------------------------------

@router.get("/customer-profile")
async def get_customer_profile(
    shop_id: str,
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """Fetch lightweight customer profile header, credits, membership, and total counts."""
    from app.core.security import verify_customer_token
    from app.models.customer import Customer
    from app.models.shop import Shop
    from app.models.membership import CustomerRetailerMembership
    from app.models.discount import Discount
    from app.models.order import Order
    from app.models.contest import ContestParticipation

    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]

    mobile = verify_customer_token(token) if token else None

    customer_info = {
        "name": "Guest Customer",
        "mobile_number": mobile or "",
        "is_member": False,
        "is_strict_member": False,
        "credit_limit": 0,
        "used_credit": 0,
        "available_credit": 0,
        "counts": {
            "visited_shops": 0,
            "orders": 0,
            "rewards": 0,
            "contests": 0
        }
    }

    try:
        shop_uuid = uuid.UUID(shop_id)
        shop_result = await db.execute(select(Shop).where(Shop.id == shop_uuid))
        shop_obj = shop_result.scalar_one_or_none()
        shop_name = shop_obj.name if shop_obj else "Store Network"
    except Exception:
        shop_name = "Store Network"
        shop_uuid = None

    if mobile:
        mobile_variants = _get_phone_variants(mobile)
        c_result = await db.execute(select(Customer).where(Customer.mobile_number.in_(mobile_variants)))
        customer_obj = c_result.scalars().first()

        if customer_obj:
            customer_info["name"] = customer_obj.name or "Customer"
            customer_info["mobile_number"] = customer_obj.mobile_number

            if shop_uuid:
                m_result = await db.execute(
                    select(CustomerRetailerMembership).where(
                        CustomerRetailerMembership.customer_id == customer_obj.id,
                        CustomerRetailerMembership.shop_id == shop_uuid
                    )
                )
                membership = m_result.scalar_one_or_none()
                if membership:
                    customer_info["is_member"] = True
                    customer_info["is_strict_member"] = membership.is_retailer_added

            # Total Orders count & Credits calculation (includes rejected/cancelled orders)
            orders_count_res = await db.execute(
                select(func.count(Order.id), func.coalesce(func.sum(Order.total_amount), 0))
                .where(Order.customer_phone.in_(mobile_variants))
            )
            total_orders_count, total_spent = orders_count_res.first() or (0, 0)
            from app.models.contest import ContestCredit
            cc_res = await db.execute(select(ContestCredit).where(ContestCredit.customer_id == customer_obj.id))
            contest_credit_obj = cc_res.scalar_one_or_none()
            contest_credits = float(contest_credit_obj.credits) if contest_credit_obj else 0.0
            customer_info["contest_credits"] = round(contest_credits, 2)
            customer_info["credit_limit"] = round(contest_credits, 2)
            customer_info["available_credit"] = round(contest_credits, 2)
            customer_info["counts"]["orders"] = total_orders_count

            # Visited Shops Count
            vshops_res = await db.execute(
                select(func.count(func.distinct(Order.shop_id)))
                .where(Order.customer_phone.in_(mobile_variants))
            )
            visited_shops_count = vshops_res.scalar() or (1 if shop_uuid else 0)
            customer_info["counts"]["visited_shops"] = max(1 if shop_uuid else 0, visited_shops_count)

            # Participated Contests Count (only count submitted entries)
            cp_count_res = await db.execute(
                select(func.count(ContestParticipation.id))
                .where(
                    ContestParticipation.customer_id == customer_obj.id,
                    ContestParticipation.is_submitted == True
                )
            )
            customer_info["counts"]["contests"] = cp_count_res.scalar() or 0

            # Active Rewards Count
            rewards_count_res = await db.execute(
                select(func.count(Discount.id))
                .where(Discount.is_active == True)
            )
            customer_info["counts"]["rewards"] = rewards_count_res.scalar() or 0

    return {
        "customer": customer_info,
        "shop": {"id": shop_id, "name": shop_name}
    }


@router.get("/customer-counts")
async def get_customer_summary_counts(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """Fetch dedicated customer summary counts only (Visited Shops, Orders, Rewards, Contests)."""
    from app.core.security import verify_customer_token
    from app.models.customer import Customer
    from app.models.discount import Discount
    from app.models.order import Order
    from app.models.contest import ContestParticipation

    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]

    mobile = verify_customer_token(token) if token else None

    counts = {
        "visited_shops": 0,
        "orders": 0,
        "rewards": 0,
        "contests": 0
    }

    if mobile:
        mobile_variants = _get_phone_variants(mobile)
        c_result = await db.execute(select(Customer).where(Customer.mobile_number.in_(mobile_variants)))
        customer_obj = c_result.scalars().first()

        if customer_obj:
            # 1. Total Orders Count (including rejected/cancelled/completed)
            orders_res = await db.execute(
                select(func.count(Order.id))
                .where(Order.customer_phone.in_(mobile_variants))
            )
            counts["orders"] = orders_res.scalar() or 0

            # 2. Visited Shops Count
            vshops_res = await db.execute(
                select(func.count(func.distinct(Order.shop_id)))
                .where(Order.customer_phone.in_(mobile_variants))
            )
            counts["visited_shops"] = vshops_res.scalar() or 0

            # 3. Participated Contests Count (only count submitted entries)
            cp_res = await db.execute(
                select(func.count(ContestParticipation.id))
                .where(
                    ContestParticipation.customer_id == customer_obj.id,
                    ContestParticipation.is_submitted == True
                )
            )
            counts["contests"] = cp_res.scalar() or 0

            # 4. Active Rewards Count
            rewards_res = await db.execute(
                select(func.count(Discount.id))
                .where(Discount.is_active == True)
            )
            counts["rewards"] = rewards_res.scalar() or 0

    return {
        "success": True,
        "counts": counts
    }


@router.get("/customer-visited-shops")
async def get_customer_visited_shops(
    shop_id: str,
    search: Optional[str] = Query(None),
    min_orders: Optional[int] = Query(None),
    sort_by: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(5, ge=1, le=100),
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
):
    from app.core.security import verify_customer_token
    from app.models.shop import Shop
    from app.models.order import Order
    import math

    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
    mobile = verify_customer_token(token) if token else None

    visited_shops_map = {}
    if mobile:
        mobile_variants = _get_phone_variants(mobile)
        ord_result = await db.execute(
            select(Order)
            .options(selectinload(Order.shop))
            .where(Order.customer_phone.in_(mobile_variants))
        )
        orders_obj = ord_result.scalars().all()
        for o in orders_obj:
            s_id = str(o.shop_id)
            if s_id not in visited_shops_map:
                visited_shops_map[s_id] = {
                    "id": s_id,
                    "name": o.shop.name if o.shop else "Menukit Store",
                    "logo_url": getattr(o.shop, "logo_url", None) if o.shop else None,
                    "total_orders": 0,
                    "total_spent": 0.0,
                    "status": "Active Store"
                }
            if str(o.order_status).lower() == "completed":
                visited_shops_map[s_id]["total_orders"] += 1
                visited_shops_map[s_id]["total_spent"] += float(o.total_amount)

    visited_shops_list = list(visited_shops_map.values())
    if not visited_shops_list and shop_id:
        try:
            shop_uuid = uuid.UUID(shop_id)
            shop_result = await db.execute(select(Shop).where(Shop.id == shop_uuid))
            shop_obj = shop_result.scalar_one_or_none()
            if shop_obj:
                visited_shops_list.append({
                    "id": str(shop_obj.id),
                    "name": shop_obj.name,
                    "logo_url": getattr(shop_obj, "logo_url", None),
                    "total_orders": 0,
                    "total_spent": 0.0,
                    "status": "Current Store"
                })
        except Exception:
            pass

    q = (search or "").strip().lower()
    if q:
        visited_shops_list = [s for s in visited_shops_list if q in s["name"].lower()]

    if min_orders and min_orders > 0:
        visited_shops_list = [s for s in visited_shops_list if s["total_orders"] >= min_orders]

    if sort_by == "most_orders":
        visited_shops_list.sort(key=lambda s: s["total_orders"], reverse=True)
    elif sort_by == "highest_spent":
        visited_shops_list.sort(key=lambda s: s["total_spent"], reverse=True)
    elif sort_by == "name":
        visited_shops_list.sort(key=lambda s: s["name"].lower())

    total_items = len(visited_shops_list)
    total_pages = math.ceil(total_items / limit) or 1
    start_idx = (page - 1) * limit
    paginated_items = visited_shops_list[start_idx : start_idx + limit]

    return {
        "items": paginated_items,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total_items,
            "total_pages": total_pages
        }
    }


@router.get("/customer-orders")
async def get_customer_orders(
    shop_id: str,
    search: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(5, ge=1, le=100),
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
):
    from app.core.security import verify_customer_token
    from app.models.order import Order
    from sqlalchemy.orm import selectinload
    from sqlalchemy import or_, cast, String
    import math

    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
    mobile = verify_customer_token(token) if token else None

    if not mobile:
        return {"items": [], "pagination": {"page": 1, "limit": limit, "total": 0, "total_pages": 1}}

    mobile_variants = _get_phone_variants(mobile)
    query = (
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.shop))
        .where(Order.customer_phone.in_(mobile_variants))
    )


    q = (search or "").strip()
    if q:
        query = query.where(
            or_(
                cast(Order.id, String).ilike(f"%{q}%"),
                Order.order_status.ilike(f"%{q}%"),
                Order.payment_status.ilike(f"%{q}%")
            )
        )

    if status_filter and status_filter.lower() != "all":
        sf = status_filter.lower()
        if sf in ["rejected", "cancelled", "rejected_cancelled"]:
            query = query.where(Order.order_status.in_(["rejected", "cancelled"]))
        else:
            query = query.where(Order.order_status.ilike(status_filter))

    count_query = select(func.count()).select_from(query.subquery())
    total_res = await db.execute(count_query)
    total_items = total_res.scalar() or 0
    total_pages = math.ceil(total_items / limit) or 1

    if sort_by == "amount_high":
        query = query.order_by(Order.total_amount.desc())
    elif sort_by == "oldest":
        query = query.order_by(Order.created_at.asc())
    else:
        query = query.order_by(Order.created_at.desc())

    query = query.offset((page - 1) * limit).limit(limit)
    orders_res = await db.execute(query)
    orders_obj = orders_res.scalars().all()

    orders_list = []
    for o in orders_obj:
        orders_list.append({
            "id": str(o.id),
            "shop_id": str(o.shop_id) if o.shop_id else shop_id,
            "shop_name": o.shop.name if o.shop else "Store Network",
            "order_status": o.order_status,
            "payment_status": o.payment_status,
            "payment_method": o.payment_method,
            "total_amount": float(o.total_amount),
            "created_at": o.created_at.isoformat() if o.created_at else "",
            "items": [
                {
                    "name": getattr(item, "name", "Item"),
                    "quantity": getattr(item, "quantity", 1),
                    "price": float(getattr(item, "price", 0))
                }
                for item in o.items
            ]
        })

    return {
        "items": orders_list,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total_items,
            "total_pages": total_pages
        }
    }


@router.get("/customer-rewards")
async def get_customer_rewards(
    shop_id: str,
    search: Optional[str] = Query(None),
    discount_type: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(5, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    from app.models.discount import Discount
    from sqlalchemy.orm import selectinload
    from sqlalchemy import or_
    import math

    query = (
        select(Discount)
        .options(selectinload(Discount.shop))
        .where(Discount.is_active == True)
    )

    q = (search or "").strip()
    if q:
        query = query.where(
            or_(
                Discount.title.ilike(f"%{q}%"),
                Discount.description.ilike(f"%{q}%")
            )
        )

    if discount_type and discount_type.lower() != "all":
        dt = discount_type.lower()
        if dt in ["bogo", "combo", "bogo_combo"]:
            query = query.where(Discount.discount_type.in_(["bogo", "combo"]))
        else:
            query = query.where(Discount.discount_type.ilike(discount_type))

    count_query = select(func.count()).select_from(query.subquery())
    total_res = await db.execute(count_query)
    total_items = total_res.scalar() or 0
    total_pages = math.ceil(total_items / limit) or 1

    if sort_by == "oldest":
        query = query.order_by(Discount.created_at.asc())
    else:
        query = query.order_by(Discount.created_at.desc())

    query = query.offset((page - 1) * limit).limit(limit)
    disc_res = await db.execute(query)
    discounts = disc_res.scalars().all()

    rewards_list = []
    for d in discounts:
        s_name = d.shop.name if d.shop else "Store Network"
        desc = d.description or (f"Flat {d.discount_value}% OFF on your order" if d.discount_type == "percentage" else f"Flat ₹{d.discount_value} OFF")
        rewards_list.append({
            "id": str(d.id),
            "shop_id": str(d.shop_id) if d.shop_id else None,
            "title": d.title,
            "description": desc,
            "shopName": s_name,
            "rewardType": "Store Offer",
            "code": getattr(d, "code", None),
            "status": "READY TO USE"
        })

    return {
        "items": rewards_list,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total_items,
            "total_pages": total_pages
        }
    }


@router.get("/customer-contests")
async def get_customer_contests(
    shop_id: str,
    type: str = Query("live"),  # 'participated' | 'live'
    search: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(5, ge=1, le=100),
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
):
    from app.core.security import verify_customer_token
    from app.models.customer import Customer
    from app.models.contest import Contest, ContestParticipation
    from sqlalchemy.orm import selectinload
    from sqlalchemy import or_
    import math

    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
    mobile = verify_customer_token(token) if token else None

    if type == "participated":
        if not mobile:
            return {"items": [], "pagination": {"page": 1, "limit": limit, "total": 0, "total_pages": 1}}

        c_result = await db.execute(select(Customer).where(Customer.mobile_number == mobile))
        customer_obj = c_result.scalar_one_or_none()
        if not customer_obj:
            return {"items": [], "pagination": {"page": 1, "limit": limit, "total": 0, "total_pages": 1}}

        cp_query = (
            select(ContestParticipation)
            .options(selectinload(ContestParticipation.contest).selectinload(Contest.shop))
            .where(
                ContestParticipation.customer_id == customer_obj.id,
                ContestParticipation.is_submitted == True
            )
        )

        q = (search or "").strip()
        if q:
            cp_query = cp_query.join(Contest).where(
                or_(
                    Contest.title.ilike(f"%{q}%"),
                    Contest.description.ilike(f"%{q}%")
                )
            )

        count_res = await db.execute(select(func.count()).select_from(cp_query.subquery()))
        total_items = count_res.scalar() or 0
        total_pages = math.ceil(total_items / limit) or 1

        cp_query = cp_query.offset((page - 1) * limit).limit(limit)
        cp_res = await db.execute(cp_query)
        cp_list = cp_res.scalars().all()

        participated_list = []
        for idx, cp in enumerate(cp_list):
            if cp.contest:
                participated_list.append({
                    "id": str(cp.contest.id),
                    "shop_id": str(cp.contest.shop_id) if cp.contest.shop_id else None,
                    "title": cp.contest.title,
                    "shopName": cp.contest.shop.name if cp.contest.shop else "Store Network",
                    "rank": (page - 1) * limit + idx + 1,
                    "pointsScore": f"{getattr(cp, 'likes_count', 0) * 10} pts",
                    "rewardWon": cp.contest.reward_value or "Special Prize",
                    "status": "LIVE NOW" if cp.contest.status == "active" else "COMPLETED"
                })

        return {
            "items": participated_list,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total_items,
                "total_pages": total_pages
            }
        }
    else:
        # Live contests
        query = (
            select(Contest)
            .options(selectinload(Contest.shop))
            .where(Contest.status == "active")
        )

        q = (search or "").strip()
        if q:
            query = query.where(
                or_(
                    Contest.title.ilike(f"%{q}%"),
                    Contest.description.ilike(f"%{q}%"),
                    Contest.reward_value.ilike(f"%{q}%")
                )
            )

        count_res = await db.execute(select(func.count()).select_from(query.subquery()))
        total_items = count_res.scalar() or 0
        total_pages = math.ceil(total_items / limit) or 1

        query = query.order_by(Contest.created_at.desc()).offset((page - 1) * limit).limit(limit)
        c_res = await db.execute(query)
        live_contests = c_res.scalars().all()

        live_list = [
            {
                "id": str(c.id),
                "shop_id": str(c.shop_id) if c.shop_id else None,
                "title": c.title,
                "description": c.description,
                "shopName": c.shop.name if c.shop else "Store Network",
                "prize_description": c.reward_value or "Free Meal Voucher",
                "ends_at": c.ends_at.isoformat() if c.ends_at else ""
            }
            for c in live_contests
        ]

        return {
            "items": live_list,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total_items,
                "total_pages": total_pages
            }
        }
