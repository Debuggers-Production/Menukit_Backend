"""Menu item management API endpoints."""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.core.deps import get_current_user
from app.schemas.menu_item import (
    MenuItemCreate, MenuItemUpdate, MenuItemReorder,
    MenuItemResponse, MenuImageResponse,
)
from app.schemas.common import MessageResponse
from app.services.menu_service import MenuService
from app.services.shop_service import ShopService
from app.services.image_scraper_service import ImageScraperService
from app.services.upload_service import UploadService
from app.models.user import User
from app.models.menu_image import MenuImage
from sqlalchemy import select, func
from pydantic import BaseModel
router = APIRouter(prefix="/menu-items", tags=["Menu Item Management"])


@router.post("", response_model=MenuItemResponse)
async def create_menu_item(
    data: MenuItemCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new menu item."""
    service = MenuService(db)
    item = await service.create_menu_item(user.id, data.model_dump())
    return _item_response(item)


@router.get("", response_model=List[MenuItemResponse])
async def get_menu_items(
    category_id: Optional[str] = Query(None),
    food_type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all menu items with optional filters."""
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_user(user.id)
    if not shop:
        return []

    service = MenuService(db)
    items = await service.get_menu_items(
        shop.id,
        category_id=uuid.UUID(category_id) if category_id else None,
        food_type=food_type,
        search=search,
    )
    
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"get_menu_items retrieved {len(items)} items")
    
    return [_item_response(i) for i in items]


@router.get("/{item_id}", response_model=MenuItemResponse)
async def get_menu_item(
    item_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single menu item."""
    service = MenuService(db)
    item = await service.get_menu_item(uuid.UUID(item_id))
    if not item:
        from app.core.exceptions import NotFoundException
        raise NotFoundException("Menu item not found")
        
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"get_menu_item retrieved item {item_id}")
        
    return _item_response(item)


@router.put("/{item_id}", response_model=MenuItemResponse)
async def update_menu_item(
    item_id: str,
    data: MenuItemUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a menu item."""
    service = MenuService(db)
    item = await service.update_menu_item(user.id, uuid.UUID(item_id), data.model_dump(exclude_none=True))
    return _item_response(item)


@router.delete("/{item_id}", response_model=MessageResponse)
async def delete_menu_item(
    item_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a menu item."""
    service = MenuService(db)
    await service.delete_menu_item(user.id, uuid.UUID(item_id))
    return MessageResponse(message="Menu item deleted successfully")


@router.put("/reorder/batch", response_model=MessageResponse)
async def reorder_items(
    data: MenuItemReorder,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reorder menu items."""
    service = MenuService(db)
    await service.reorder_menu_items(user.id, data.order)
    return MessageResponse(message="Items reordered successfully")


@router.delete("/{item_id}/images/{image_id}", response_model=MessageResponse)
async def delete_menu_image(
    item_id: str,
    image_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a menu item image."""
    service = MenuService(db)
    await service.delete_menu_image(user.id, uuid.UUID(item_id), uuid.UUID(image_id))
    return MessageResponse(message="Image deleted successfully")


@router.put("/{item_id}/images/{image_id}/primary", response_model=MessageResponse)
async def set_primary_image(
    item_id: str,
    image_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set a menu item image as primary."""
    service = MenuService(db)
    await service.set_primary_menu_image(user.id, uuid.UUID(item_id), uuid.UUID(image_id))
    return MessageResponse(message="Primary image updated successfully")


from sqlalchemy import inspect

class ImageUrlRequest(BaseModel):
    url: str

@router.get("/{item_id}/search-images")
async def search_item_images(
    item_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Search for food images and return a list of URLs for the user to choose from.
    """
    menu_service = MenuService(db)
    shop_service = ShopService(db)

    shop = await shop_service.get_shop_by_user(user.id)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    item = await menu_service.get_menu_item(uuid.UUID(item_id))
    if not item or item.shop_id != shop.id:
        raise HTTPException(status_code=404, detail="Menu item not found")

    scraper = ImageScraperService()
    urls = await scraper.search_image_urls(item.name)
    return {"urls": urls}

@router.post("/{item_id}/save-image-url", response_model=MenuImageResponse)
async def save_item_image_url(
    item_id: str,
    payload: ImageUrlRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Download a specific image URL and save it to the menu item.
    """
    menu_service = MenuService(db)
    shop_service = ShopService(db)

    shop = await shop_service.get_shop_by_user(user.id)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    item = await menu_service.get_menu_item(uuid.UUID(item_id))
    if not item or item.shop_id != shop.id:
        raise HTTPException(status_code=404, detail="Menu item not found")

    scraper = ImageScraperService()
    result = await scraper.download_image_url(payload.url)
    if not result:
        raise HTTPException(status_code=400, detail="Could not download the selected image.")

    image_bytes, content_type = result
    
    # Check if this is the first image
    result_images = await db.execute(
        select(func.count(MenuImage.id)).where(MenuImage.menu_item_id == item.id)
    )
    existing_count = result_images.scalar() or 0
    is_primary = (existing_count == 0)

    # Upload and save
    upload_service = UploadService()
    
    try:
        upload_result = await upload_service.upload_image_from_bytes(
            image_bytes=image_bytes,
            folder=f"menu-items/{shop.id}",
        )
        menu_image = await menu_service.add_menu_image(
            item_id=item.id,
            image_url=upload_result["image_url"],
            thumbnail_url=upload_result["thumbnail_url"],
            is_primary=is_primary
        )
        await db.commit()
        return MenuImageResponse(
            id=str(menu_image.id),
            image_url=menu_image.image_url,
            thumbnail_url=menu_image.thumbnail_url,
            is_primary=menu_image.is_primary,
            display_order=menu_image.display_order,
            created_at=menu_image.created_at,
        )
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to save image: {str(e)}")

@router.post("/{item_id}/auto-image", response_model=MenuImageResponse)
async def auto_fetch_item_image(
    item_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Auto-scrape a food image for a menu item that has no image.
    Downloads from Unsplash/DuckDuckGo, uploads to MinIO, and saves as primary image.
    """
    menu_service = MenuService(db)
    shop_service = ShopService(db)

    # Ensure the item belongs to this user's shop
    shop = await shop_service.get_shop_by_user(user.id)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    item = await menu_service.get_menu_item(uuid.UUID(item_id))
    if not item or item.shop_id != shop.id:
        raise HTTPException(status_code=404, detail="Menu item not found")

    # Scrape the image
    scraper = ImageScraperService()
    result = await scraper.fetch_food_image(item.name)
    if not result:
        raise HTTPException(
            status_code=502,
            detail="Could not find an image for this item. Try again or upload one manually."
        )

    image_bytes, mime_type = result

    # Upload to MinIO via the existing pipeline
    try:
        upload_service = UploadService()
        upload_result = await upload_service.upload_image_from_bytes(
            image_bytes=image_bytes,
            folder=f"menu-items/{shop.id}",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Image upload failed: {str(e)}")

    # Save as primary MenuImage
    image = await menu_service.add_menu_image(
        item_id=uuid.UUID(item_id),
        image_url=upload_result["image_url"],
        thumbnail_url=upload_result["thumbnail_url"],
        is_primary=True,
    )

    return MenuImageResponse(
        id=str(image.id),
        image_url=image.image_url,
        thumbnail_url=image.thumbnail_url,
        is_primary=image.is_primary,
        display_order=image.display_order,
    )


def _item_response(item, avg_rating: float = None, review_count: int = 0) -> MenuItemResponse:
    """Convert MenuItem model to response."""
    image_url = None
    thumbnail_url = None
    images_list = []
    state = inspect(item)
    if "images" not in state.unloaded and hasattr(item, "images") and item.images:
        # Find the primary images, and use the newest one. If none, use the newest uploaded image.
        primaries = [img for img in item.images if img.is_primary]
        if primaries:
            primary = sorted(primaries, key=lambda x: x.created_at, reverse=True)[0]
        else:
            primary = sorted(item.images, key=lambda x: x.created_at, reverse=True)[0]
            
        image_url = primary.image_url
        thumbnail_url = primary.thumbnail_url
        
        images_list = [
            MenuImageResponse(
                id=str(img.id),
                image_url=img.image_url,
                thumbnail_url=img.thumbnail_url,
                is_primary=img.is_primary,
                display_order=img.display_order
            ) for img in sorted(item.images, key=lambda x: (not x.is_primary, x.display_order))
        ]

    # Use pre-loaded rating if provided, otherwise use attrs set on item directly
    final_avg = avg_rating if avg_rating is not None else getattr(item, '_avg_rating', None)
    final_count = review_count if review_count else getattr(item, '_review_count', 0)

    return MenuItemResponse(
        id=str(item.id),
        category_id=str(item.category_id),
        name=item.name,
        description=item.description,
        price=str(item.price),
        offer_price=str(item.offer_price) if item.offer_price else None,
        food_type=item.food_type,
        allow_ice_preference=item.allow_ice_preference,
        is_bestseller=item.is_bestseller,
        is_highlighted=item.is_highlighted,
        is_available=item.is_available,
        display_order=item.display_order,
        image_url=image_url,
        thumbnail_url=thumbnail_url,
        images=images_list,
        variants=item.variants,
        addons=item.addons,
        average_rating=round(final_avg, 1) if final_avg else None,
        review_count=final_count,
        created_at=str(item.created_at),
    )


@router.get("/{item_id}/reviews")
async def get_item_reviews(
    item_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all reviews for a menu item (owner view)."""
    from sqlalchemy import select, func
    from app.models.review import MenuItemReview
    from app.schemas.review import ReviewResponse, ReviewSummary

    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_user(user.id)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    item = await MenuService(db).get_menu_item(uuid.UUID(item_id))
    if not item or item.shop_id != shop.id:
        raise HTTPException(status_code=404, detail="Menu item not found")

    result = await db.execute(
        select(MenuItemReview)
        .where(MenuItemReview.menu_item_id == uuid.UUID(item_id))
        .order_by(MenuItemReview.created_at.desc())
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
