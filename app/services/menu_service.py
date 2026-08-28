"""Menu management service for categories and items."""

import uuid
from typing import Optional, List

from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.category import Category
from app.models.menu_item import MenuItem
from app.models.menu_image import MenuImage
from app.models.activity_log import ActivityLog
from app.models.shop import Shop
from app.core.exceptions import NotFoundException, ForbiddenException
from app.services.upload_service import UploadService


class MenuService:
    """Handles menu category and item CRUD operations."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.upload_service = UploadService()

    async def _get_user_shop(self, user_id: uuid.UUID) -> Shop:
        """Get the shop owned by the user."""
        result = await self.db.execute(select(Shop).where(Shop.user_id == user_id))
        shop = result.scalar_one_or_none()
        if not shop:
            raise NotFoundException("Shop not found. Create a shop first.")
        return shop

    async def _get_catalog_id(self, shop_id: uuid.UUID) -> uuid.UUID:
        """Resolve the menu_catalog_id for a given shop."""
        result = await self.db.execute(
            select(Shop.menu_catalog_id).where(Shop.id == shop_id)
        )
        catalog_id = result.scalar_one_or_none()
        if not catalog_id:
            raise NotFoundException("This shop has no linked menu catalog. Please contact support.")
        return catalog_id

    # ── Categories ────────────────────────────────────────────

    async def create_category(self, shop_id: uuid.UUID, user_id: uuid.UUID, data: dict) -> Category:
        """Create a new menu category linked to the shop's catalog."""
        catalog_id = await self._get_catalog_id(shop_id)
        category = Category(menu_catalog_id=catalog_id, **data)
        self.db.add(category)

        activity = ActivityLog(user_id=user_id, action="category_create", details=f"Created category: {data['name']}")
        self.db.add(activity)

        await self.db.flush()
        return category

    async def get_categories(
        self, shop_id: uuid.UUID, skip: int = 0, limit: int = 100, search: Optional[str] = None
    ) -> tuple[List[Category], int, bool]:
        """Get all categories for a shop's catalog with backend search and pagination."""
        catalog_id = await self._get_catalog_id(shop_id)
        conditions = [Category.menu_catalog_id == catalog_id]

        if search and search.strip():
            term = f"%{search.strip()}%"
            conditions.append(Category.name.ilike(term))

        count_stmt = select(func.count(Category.id)).where(*conditions)
        count_res = await self.db.execute(count_stmt)
        total_count = count_res.scalar() or 0

        result = await self.db.execute(
            select(Category)
            .where(*conditions)
            .order_by(Category.display_order)
            .offset(skip)
            .limit(limit)
        )
        categories = list(result.scalars().all())
        has_more = (skip + len(categories)) < total_count

        return categories, total_count, has_more

    async def update_category(self, shop_id: uuid.UUID, user_id: uuid.UUID, category_id: uuid.UUID, data: dict) -> Category:
        """Update a category."""
        catalog_id = await self._get_catalog_id(shop_id)
        result = await self.db.execute(
            select(Category).where(Category.id == category_id, Category.menu_catalog_id == catalog_id)
        )
        category = result.scalar_one_or_none()
        if not category:
            raise NotFoundException("Category not found")

        # Delete old category image if a new image_url is provided
        if "image_url" in data and data["image_url"] and category.image_url and data["image_url"] != category.image_url:
            try:
                from app.services.upload_service import UploadService
                await UploadService().delete_image_by_url(category.image_url)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Failed to delete old category image: {e}")

        for key, value in data.items():
            if value is not None and hasattr(category, key):
                setattr(category, key, value)

        activity = ActivityLog(user_id=user_id, action="category_update", details=f"Updated category: {category.name}")
        self.db.add(activity)

        await self.db.flush()
        return category

    async def delete_category(self, shop_id: uuid.UUID, user_id: uuid.UUID, category_id: uuid.UUID):
        """Delete a category and all its items."""
        catalog_id = await self._get_catalog_id(shop_id)
        result = await self.db.execute(
            select(Category).where(Category.id == category_id, Category.menu_catalog_id == catalog_id)
        )
        category = result.scalar_one_or_none()
        if not category:
            raise NotFoundException("Category not found")

        # Clean up images of menu items in this category
        items_res = await self.db.execute(
            select(MenuItem)
            .options(selectinload(MenuItem.images))
            .where(MenuItem.category_id == category_id)
        )
        items = list(items_res.scalars().all())
        for item in items:
            for img in item.images:
                if img.image_url:
                    await self.upload_service.delete_image_by_url(img.image_url)
                if img.thumbnail_url and img.thumbnail_url != img.image_url:
                    await self.upload_service.delete_image_by_url(img.thumbnail_url)

        if category.image_url:
            await self.upload_service.delete_image_by_url(category.image_url)

        activity = ActivityLog(user_id=user_id, action="category_delete", details=f"Deleted category: {category.name}")
        self.db.add(activity)

        await self.db.delete(category)
        await self.db.flush()

    async def delete_all_categories(self, shop_id: uuid.UUID, user_id: uuid.UUID):
        """Delete all categories (and their items) for the shop's catalog."""
        catalog_id = await self._get_catalog_id(shop_id)

        # Clean up category images & item images
        cats_res = await self.db.execute(
            select(Category).where(Category.menu_catalog_id == catalog_id)
        )
        cats = list(cats_res.scalars().all())
        for cat in cats:
            if cat.image_url:
                await self.upload_service.delete_image_by_url(cat.image_url)

        items_res = await self.db.execute(
            select(MenuItem)
            .options(selectinload(MenuItem.images))
            .where(MenuItem.menu_catalog_id == catalog_id)
        )
        items = list(items_res.scalars().all())
        for item in items:
            for img in item.images:
                if img.image_url:
                    await self.upload_service.delete_image_by_url(img.image_url)
                if img.thumbnail_url and img.thumbnail_url != img.image_url:
                    await self.upload_service.delete_image_by_url(img.thumbnail_url)

        await self.db.execute(
            delete(Category).where(Category.menu_catalog_id == catalog_id)
        )
        activity = ActivityLog(
            user_id=user_id,
            action="category_delete_all",
            details="Deleted all categories",
        )
        self.db.add(activity)
        await self.db.flush()

    async def reorder_categories(self, shop_id: uuid.UUID, user_id: uuid.UUID, order: List[dict]):
        """Reorder categories."""
        catalog_id = await self._get_catalog_id(shop_id)
        for item in order:
            item_id = item["id"] if isinstance(item, dict) else getattr(item, "id")

            result = await self.db.execute(
                select(Category).where(
                    Category.id == uuid.UUID(str(item_id)),
                    Category.menu_catalog_id == catalog_id,
                )
            )
            category = result.scalar_one_or_none()
            if category:
                display_order = item["display_order"] if isinstance(item, dict) else getattr(item, "display_order")
                category.display_order = display_order
        await self.db.flush()

    # ── Menu Items ────────────────────────────────────────────

    async def create_menu_item(self, shop_id: uuid.UUID, user_id: uuid.UUID, data: dict) -> MenuItem:
        """Create a new menu item."""
        catalog_id = await self._get_catalog_id(shop_id)

        category_id_str = data.pop("category_id")
        category = None
        try:
            category_id = uuid.UUID(category_id_str)
            result = await self.db.execute(
                select(Category).where(Category.id == category_id, Category.menu_catalog_id == catalog_id)
            )
            category = result.scalar_one_or_none()
        except ValueError:
            # If not a valid UUID, treat it as a category name and find or create it
            result = await self.db.execute(
                select(Category).where(
                    func.lower(Category.name) == category_id_str.lower(),
                    Category.menu_catalog_id == catalog_id
                )
            )
            category = result.scalar_one_or_none()
            if not category:
                # Auto-create the category to make bulk uploads seamless
                category = Category(menu_catalog_id=catalog_id, name=category_id_str)
                self.db.add(category)
                await self.db.flush()

        if not category:
            raise NotFoundException(f"Category '{category_id_str}' not found")

        item = MenuItem(menu_catalog_id=catalog_id, category_id=category.id, **data)
        self.db.add(item)

        activity = ActivityLog(user_id=user_id, action="menu_create", details=f"Created item: {data['name']}")
        self.db.add(activity)

        await self.db.flush()
        return item

    async def get_menu_items(
        self,
        shop_id: uuid.UUID,
        category_id: Optional[uuid.UUID] = None,
        food_type: Optional[str] = None,
        search: Optional[str] = None,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[MenuItem]:
        """Get menu items with optional filters and pagination."""
        catalog_id = await self._get_catalog_id(shop_id)
        query = (
            select(MenuItem)
            .options(selectinload(MenuItem.images))
            .where(MenuItem.menu_catalog_id == catalog_id)
        )

        if category_id:
            query = query.where(MenuItem.category_id == category_id)
        if food_type:
            query = query.where(MenuItem.food_types.contains([food_type]))
        if search:
            query = query.where(MenuItem.name.ilike(f"%{search}%"))
        if status:
            if status == "available":
                query = query.where(MenuItem.is_available == True)
            elif status == "not_available":
                query = query.where(MenuItem.is_available == False)
            elif status == "bestseller":
                query = query.where(MenuItem.is_bestseller == True)
            elif status == "chef_special":
                query = query.where(MenuItem.is_highlighted == True)

        query = query.order_by(MenuItem.display_order).offset(skip).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_menu_item(self, item_id: uuid.UUID) -> Optional[MenuItem]:
        """Get a single menu item."""
        result = await self.db.execute(
            select(MenuItem).options(selectinload(MenuItem.images)).where(MenuItem.id == item_id)
        )
        return result.scalar_one_or_none()

    async def update_menu_item(self, shop_id: uuid.UUID, user_id: uuid.UUID, item_id: uuid.UUID, data: dict) -> MenuItem:
        """Update a menu item."""
        catalog_id = await self._get_catalog_id(shop_id)
        result = await self.db.execute(
            select(MenuItem)
            .options(selectinload(MenuItem.images))
            .where(MenuItem.id == item_id, MenuItem.menu_catalog_id == catalog_id)
        )
        item = result.scalar_one_or_none()
        if not item:
            raise NotFoundException("Menu item not found")

        # Handle category_id separately since it needs UUID conversion
        if "category_id" in data and data["category_id"]:
            data["category_id"] = uuid.UUID(data["category_id"])

        for key, value in data.items():
            if value is not None and hasattr(item, key):
                setattr(item, key, value)

        activity = ActivityLog(user_id=user_id, action="menu_update", details=f"Updated item: {item.name}")
        self.db.add(activity)

        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def delete_menu_item(self, shop_id: uuid.UUID, user_id: uuid.UUID, item_id: uuid.UUID):
        """Delete a menu item."""
        catalog_id = await self._get_catalog_id(shop_id)
        result = await self.db.execute(
            select(MenuItem)
            .options(selectinload(MenuItem.images))
            .where(MenuItem.id == item_id, MenuItem.menu_catalog_id == catalog_id)
        )
        item = result.scalar_one_or_none()
        if not item:
            raise NotFoundException("Menu item not found")

        for img in item.images:
            if img.image_url:
                await self.upload_service.delete_image_by_url(img.image_url)
            if img.thumbnail_url and img.thumbnail_url != img.image_url:
                await self.upload_service.delete_image_by_url(img.thumbnail_url)

        activity = ActivityLog(user_id=user_id, action="menu_delete", details=f"Deleted item: {item.name}")
        self.db.add(activity)

        await self.db.delete(item)
        await self.db.flush()

    async def delete_all_menu_items(self, shop_id: uuid.UUID, user_id: uuid.UUID):
        """Delete all menu items for the user's shop's catalog."""
        catalog_id = await self._get_catalog_id(shop_id)
        items_res = await self.db.execute(
            select(MenuItem)
            .options(selectinload(MenuItem.images))
            .where(MenuItem.menu_catalog_id == catalog_id)
        )
        items = list(items_res.scalars().all())
        for item in items:
            for img in item.images:
                if img.image_url:
                    await self.upload_service.delete_image_by_url(img.image_url)
                if img.thumbnail_url and img.thumbnail_url != img.image_url:
                    await self.upload_service.delete_image_by_url(img.thumbnail_url)

        await self.db.execute(
            delete(MenuItem).where(MenuItem.menu_catalog_id == catalog_id)
        )
        activity = ActivityLog(
            user_id=user_id,
            action="menu_delete_all",
            details="Deleted all menu items",
        )
        self.db.add(activity)
        await self.db.flush()

    async def reorder_menu_items(self, shop_id: uuid.UUID, user_id: uuid.UUID, order: List[dict]):
        """Reorder menu items."""
        catalog_id = await self._get_catalog_id(shop_id)
        for entry in order:
            result = await self.db.execute(
                select(MenuItem).where(
                    MenuItem.id == uuid.UUID(entry["id"]),
                    MenuItem.menu_catalog_id == catalog_id,
                )
            )
            item = result.scalar_one_or_none()
            if item:
                item.display_order = entry["display_order"]
        await self.db.flush()

    async def add_menu_image(
        self,
        item_id: uuid.UUID,
        image_url: str,
        thumbnail_url: str = None,
        is_primary: bool = False
    ) -> MenuImage:

        # Verify menu item exists
        menu_item = await self.db.get(MenuItem, item_id)

        if not menu_item:
            raise ValueError("Menu item not found")

        # Check if exact image URL already exists for this item
        existing_result = await self.db.execute(
            select(MenuImage).where(MenuImage.menu_item_id == item_id, MenuImage.image_url == image_url)
        )
        existing = existing_result.scalar_one_or_none()
        if existing:
            return existing

        # Check image limit
        from sqlalchemy import func
        count_result = await self.db.execute(
            select(func.count(MenuImage.id)).where(MenuImage.menu_item_id == item_id)
        )
        current_count = count_result.scalar_one()
        if current_count >= 4:
            raise ValueError("Maximum of 4 images allowed per item")

        if is_primary:
            from sqlalchemy import update
            await self.db.execute(
                update(MenuImage)
                .where(MenuImage.menu_item_id == item_id)
                .values(is_primary=False)
            )

        image = MenuImage(
            menu_item_id=item_id,
            image_url=image_url,
            thumbnail_url=thumbnail_url,
            is_primary=is_primary,
        )

        self.db.add(image)

        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(image)

        return image

    async def delete_menu_image(self, user_id: uuid.UUID, item_id: uuid.UUID, image_id: uuid.UUID):
        shop = await self._get_user_shop(user_id)
        # Verify item belongs to shop's catalog
        catalog_id = await self._get_catalog_id(shop.id)
        item = await self.get_menu_item(item_id)
        if not item or item.menu_catalog_id != catalog_id:
            raise NotFoundException("Menu item not found")
            
        image = await self.db.get(MenuImage, image_id)
        if not image or image.menu_item_id != item_id:
            raise NotFoundException("Image not found")
            
        if image.image_url:
            await self.upload_service.delete_image_by_url(image.image_url)
        if image.thumbnail_url and image.thumbnail_url != image.image_url:
            await self.upload_service.delete_image_by_url(image.thumbnail_url)

        await self.db.delete(image)
        await self.db.flush()
        await self.db.commit()

    async def set_primary_menu_image(self, user_id: uuid.UUID, item_id: uuid.UUID, image_id: uuid.UUID):
        shop = await self._get_user_shop(user_id)
        # Verify item belongs to shop's catalog
        catalog_id = await self._get_catalog_id(shop.id)
        item = await self.get_menu_item(item_id)
        if not item or item.menu_catalog_id != catalog_id:
            raise NotFoundException("Menu item not found")
            
        image = await self.db.get(MenuImage, image_id)
        if not image or image.menu_item_id != item_id:
            raise NotFoundException("Image not found")
            
        from sqlalchemy import update
        await self.db.execute(
            update(MenuImage)
            .where(MenuImage.menu_item_id == item_id)
            .values(is_primary=False)
        )
        
        image.is_primary = True
        await self.db.flush()
        await self.db.commit()
