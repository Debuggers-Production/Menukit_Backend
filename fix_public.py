import sys

lines_to_prepend = """
from fastapi import HTTPException
from sqlalchemy import select, func
from app.models.review import MenuItemReview
from app.schemas.discount import DiscountResponse
from app.schemas.review import ReviewCreate, ReviewResponse, ReviewSummary
from datetime import date, datetime, time
"""

with open('app/api/v1/public.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Add imports if missing
if 'from app.schemas.review' not in content:
    lines = content.split('\n')
    lines.insert(10, lines_to_prepend.strip())
    content = '\n'.join(lines)

append_content = """

@router.get("/discounts", response_model=List[DiscountResponse])
async def get_active_discounts_public(
    shop_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    \"\"\"Get active discounts for public display.\"\"\"
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
    \"\"\"Submit a star review for a menu item (public, no auth required).\"\"\"
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

    # IP-based rate limit: max 3 reviews per IP per item per day
    client_ip = request.client.host if request.client else "unknown"
    today_start = datetime.combine(date.today(), time.min)
    
    existing = await db.execute(
        select(func.count(MenuItemReview.id)).where(
            MenuItemReview.menu_item_id == item_id,
            MenuItemReview.reviewer_ip == client_ip,
            MenuItemReview.created_at >= today_start,
        )
    )
    count_today = existing.scalar_one()
    if count_today >= 3:
        raise HTTPException(
            status_code=429,
            detail="You have submitted too many reviews for this item today. Please try again tomorrow."
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
    \"\"\"Get reviews summary for a specific menu item (public).\"\"\"
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
    \"\"\"Get a single menu item with rating details (public).\"\"\"
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_id(shop_id)
    if not shop:
        raise NotFoundException("Restaurant not found")

    menu_service = MenuService(db)
    item = await menu_service.get_menu_item(item_id)
    if not item or item.shop_id != shop.id:
        raise HTTPException(status_code=404, detail="Menu item not found")

    from app.api.v1.menu_items import _get_rating_map
    rating_map = await _get_rating_map(db, shop.id)
    avg_rating, review_count = rating_map.get(str(item.id), (None, 0))

    return _item_response(item, avg_rating=avg_rating, review_count=review_count)
"""

if '@router.post("/items/{item_id}/reviews"' not in content:
    content += append_content

with open('app/api/v1/public.py', 'w', encoding='utf-8') as f:
    f.write(content)
