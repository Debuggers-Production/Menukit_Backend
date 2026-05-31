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


class MenuService:
    """Handles menu category and item CRUD operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_user_shop(self, user_id: uuid.UUID) -> Shop:
        """Get the shop owned by the user."""
        result = await self.db.execute(select(Shop).where(Shop.user_id == user_id))
        shop = result.scalar_one_or_none()
        if not shop:
            raise NotFoundException("Shop not found. Create a shop first.")
        return shop

    # ── Categories ────────────────────────────────────────────

    async def create_category(self, user_id: uuid.UUID, data: dict) -> Category:
        """Create a new menu category."""
        shop = await self._get_user_shop(user_id)

        category = Category(shop_id=shop.id, **data)
        self.db.add(category)

        activity = ActivityLog(user_id=user_id, action="category_create", details=f"Created category: {data['name']}")
        self.db.add(activity)

        await self.db.flush()
        return category

    async def get_categories(self, shop_id: uuid.UUID) -> List[Category]:
        """Get all categories for a shop."""
        result = await self.db.execute(
            select(Category)
            .where(Category.shop_id == shop_id)
            .order_by(Category.display_order)
        )
        return list(result.scalars().all())

    async def update_category(self, user_id: uuid.UUID, category_id: uuid.UUID, data: dict) -> Category:
        """Update a category."""
        shop = await self._get_user_shop(user_id)
        result = await self.db.execute(
            select(Category).where(Category.id == category_id, Category.shop_id == shop.id)
        )
        category = result.scalar_one_or_none()
        if not category:
            raise NotFoundException("Category not found")

        for key, value in data.items():
            if value is not None and hasattr(category, key):
                setattr(category, key, value)

        activity = ActivityLog(user_id=user_id, action="category_update", details=f"Updated category: {category.name}")
        self.db.add(activity)

        await self.db.flush()
        return category

    async def delete_category(self, user_id: uuid.UUID, category_id: uuid.UUID):
        """Delete a category and all its items."""
        shop = await self._get_user_shop(user_id)
        result = await self.db.execute(
            select(Category).where(Category.id == category_id, Category.shop_id == shop.id)
        )
        category = result.scalar_one_or_none()
        if not category:
            raise NotFoundException("Category not found")

        activity = ActivityLog(user_id=user_id, action="category_delete", details=f"Deleted category: {category.name}")
        self.db.add(activity)

        await self.db.delete(category)
        await self.db.flush()

    async def reorder_categories(self, user_id: uuid.UUID, order: List[dict]):
        """Reorder categories."""
        shop = await self._get_user_shop(user_id)
        for item in order:
            result = await self.db.execute(
                select(Category).where(
                    Category.id == uuid.UUID(item["id"]),
                    Category.shop_id == shop.id,
                )
            )
            category = result.scalar_one_or_none()
            if category:
                category.display_order = item["display_order"]
        await self.db.flush()

    # ── Menu Items ────────────────────────────────────────────

    async def create_menu_item(self, user_id: uuid.UUID, data: dict) -> MenuItem:
        """Create a new menu item."""
        shop = await self._get_user_shop(user_id)

        # Verify category belongs to shop
        category_id = uuid.UUID(data.pop("category_id"))
        result = await self.db.execute(
            select(Category).where(Category.id == category_id, Category.shop_id == shop.id)
        )
        if not result.scalar_one_or_none():
            raise NotFoundException("Category not found")

        item = MenuItem(shop_id=shop.id, category_id=category_id, **data)
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
    ) -> List[MenuItem]:
        """Get menu items with optional filters."""
        query = (
            select(MenuItem)
            .options(selectinload(MenuItem.images))
            .where(MenuItem.shop_id == shop_id)
        )

        if category_id:
            query = query.where(MenuItem.category_id == category_id)
        if food_type:
            query = query.where(MenuItem.food_type == food_type)
        if search:
            query = query.where(MenuItem.name.ilike(f"%{search}%"))

        query = query.order_by(MenuItem.display_order)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_menu_item(self, item_id: uuid.UUID) -> Optional[MenuItem]:
        """Get a single menu item."""
        result = await self.db.execute(
            select(MenuItem).options(selectinload(MenuItem.images)).where(MenuItem.id == item_id)
        )
        return result.scalar_one_or_none()

    async def update_menu_item(self, user_id: uuid.UUID, item_id: uuid.UUID, data: dict) -> MenuItem:
        """Update a menu item."""
        shop = await self._get_user_shop(user_id)
        result = await self.db.execute(
            select(MenuItem)
            .options(selectinload(MenuItem.images))
            .where(MenuItem.id == item_id, MenuItem.shop_id == shop.id)
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

    async def delete_menu_item(self, user_id: uuid.UUID, item_id: uuid.UUID):
        """Delete a menu item."""
        shop = await self._get_user_shop(user_id)
        result = await self.db.execute(
            select(MenuItem).where(MenuItem.id == item_id, MenuItem.shop_id == shop.id)
        )
        item = result.scalar_one_or_none()
        if not item:
            raise NotFoundException("Menu item not found")

        activity = ActivityLog(user_id=user_id, action="menu_delete", details=f"Deleted item: {item.name}")
        self.db.add(activity)

        await self.db.delete(item)
        await self.db.flush()

    async def reorder_menu_items(self, user_id: uuid.UUID, order: List[dict]):
        """Reorder menu items."""
        shop = await self._get_user_shop(user_id)
        for entry in order:
            result = await self.db.execute(
                select(MenuItem).where(
                    MenuItem.id == uuid.UUID(entry["id"]),
                    MenuItem.shop_id == shop.id,
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
        # Verify item belongs to shop
        item = await self.get_menu_item(item_id)
        if not item or item.shop_id != shop.id:
            raise NotFoundException("Menu item not found")
            
        image = await self.db.get(MenuImage, image_id)
        if not image or image.menu_item_id != item_id:
            raise NotFoundException("Image not found")
            
        await self.db.delete(image)
        await self.db.flush()
        await self.db.commit()

    async def set_primary_menu_image(self, user_id: uuid.UUID, item_id: uuid.UUID, image_id: uuid.UUID):
        shop = await self._get_user_shop(user_id)
        # Verify item belongs to shop
        item = await self.get_menu_item(item_id)
        if not item or item.shop_id != shop.id:
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
