import os
import re

FILE_PATH = r"d:\projects\menu_project\menukit_backend\app\api\v1\public.py"

with open(FILE_PATH, "r", encoding="utf-8") as f:
    content = f.read()

new_func = '''@shops_router.get("", response_model=List[PublicShopListing])
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
    return listing[offset : offset + limit]'''

pattern = r'@shops_router\.get\(\"\", response_model=List\[PublicShopListing\]\)\nasync def list_public_shops\([\s\S]*?return listing'

new_content = re.sub(pattern, new_func, content)

with open(FILE_PATH, "w", encoding="utf-8") as f:
    f.write(new_content)
print("Updated list_public_shops")
