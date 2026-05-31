"""Shop management service."""

import uuid
from typing import Optional

from slugify import slugify
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.shop import Shop
from app.models.shop_settings import ShopSettings
from app.models.theme_settings import ThemeSettings
from app.models.activity_log import ActivityLog
from app.core.exceptions import NotFoundException, ConflictException


class ShopService:
    """Handles shop CRUD operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _generate_unique_slug(self, name: str) -> str:
        """Generate a unique slug from the shop name."""
        base_slug = slugify(name)
        slug = base_slug
        counter = 1

        while True:
            result = await self.db.execute(select(Shop).where(Shop.slug == slug))
            if not result.scalar_one_or_none():
                return slug
            slug = f"{base_slug}-{counter}"
            counter += 1

    async def create_shop(self, user_id: uuid.UUID, data: dict) -> Shop:
        """Create a new shop for a user."""
        # Check if user already has a shop
        result = await self.db.execute(select(Shop).where(Shop.user_id == user_id))
        existing = result.scalar_one_or_none()
        if existing:
            raise ConflictException("You already have a shop. Update it instead.")

        slug = await self._generate_unique_slug(data["name"])

        shop = Shop(
            user_id=user_id,
            slug=slug,
            **data,
        )
        self.db.add(shop)
        await self.db.flush()

        # Create default settings
        settings = ShopSettings(shop_id=shop.id)
        self.db.add(settings)
        shop.settings = settings

        # Create default theme
        theme = ThemeSettings(shop_id=shop.id)
        self.db.add(theme)
        shop.theme = theme

        # Log activity
        activity = ActivityLog(
            user_id=user_id,
            action="shop_create",
            details=f"Created shop: {shop.name}",
        )
        self.db.add(activity)

        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(shop)
        return shop

    async def get_shop_by_user(self, user_id: uuid.UUID) -> Optional[Shop]:
        """Get shop owned by user."""
        result = await self.db.execute(
            select(Shop)
            .options(selectinload(Shop.settings), selectinload(Shop.theme))
            .where(Shop.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_shop_by_slug(self, slug: str) -> Optional[Shop]:
        """Get shop by its URL slug."""
        result = await self.db.execute(
            select(Shop)
            .options(
                selectinload(Shop.settings),
                selectinload(Shop.theme),
                selectinload(Shop.categories),
            )
            .where(Shop.slug == slug, Shop.is_active == True)
        )
        return result.scalar_one_or_none()

    async def get_shop_by_id(self, shop_id: uuid.UUID) -> Optional[Shop]:
        """Get shop by its UUID."""
        result = await self.db.execute(
            select(Shop)
            .options(
                selectinload(Shop.settings),
                selectinload(Shop.theme),
                selectinload(Shop.categories),
            )
            .where(Shop.id == shop_id, Shop.is_active == True)
        )
        return result.scalar_one_or_none()

    async def update_shop(self, user_id: uuid.UUID, data: dict) -> Shop:
        """Update shop details."""
        shop = await self.get_shop_by_user(user_id)
        if not shop:
            raise NotFoundException("Shop not found")

        name_changed = "name" in data and data["name"] and data["name"] != shop.name

        for key, value in data.items():
            if hasattr(shop, key):
                setattr(shop, key, value)

        # If name changed, regenerate slug
        if name_changed:
            shop.slug = await self._generate_unique_slug(data["name"])

        # Log activity
        activity = ActivityLog(
            user_id=user_id,
            action="shop_update",
            details=f"Updated shop: {shop.name}",
        )
        self.db.add(activity)

        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(shop)
        return shop

    async def update_theme(self, user_id: uuid.UUID, data: dict) -> ThemeSettings:
        """Update theme settings."""
        shop = await self.get_shop_by_user(user_id)
        if not shop:
            raise NotFoundException("Shop not found")

        if not shop.theme:
            shop.theme = ThemeSettings(shop_id=shop.id)
            self.db.add(shop.theme)
            await self.db.flush()

        for key, value in data.items():
            if value is not None and hasattr(shop.theme, key):
                setattr(shop.theme, key, value)

        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(shop)
        return shop.theme

    async def update_settings(self, user_id: uuid.UUID, data: dict) -> ShopSettings:
        """Update shop settings."""
        shop = await self.get_shop_by_user(user_id)
        if not shop:
            raise NotFoundException("Shop not found")

        if not shop.settings:
            shop.settings = ShopSettings(shop_id=shop.id)
            self.db.add(shop.settings)
            await self.db.flush()

        for key, value in data.items():
            if value is not None and hasattr(shop.settings, key):
                setattr(shop.settings, key, value)

        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(shop)
        return shop.settings

    async def get_all_shops(self, page: int = 1, page_size: int = 20) -> dict:
        """Get all shops (admin)."""
        offset = (page - 1) * page_size
        result = await self.db.execute(
            select(Shop)
            .options(selectinload(Shop.settings), selectinload(Shop.theme))
            .offset(offset)
            .limit(page_size)
        )
        shops = result.scalars().all()

        count_result = await self.db.execute(select(func.count(Shop.id)))
        total = count_result.scalar()

        return {
            "items": shops,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }

    async def toggle_shop(self, shop_id: uuid.UUID) -> Shop:
        """Enable/disable a shop (admin)."""
        result = await self.db.execute(select(Shop).where(Shop.id == shop_id))
        shop = result.scalar_one_or_none()
        if not shop:
            raise NotFoundException("Shop not found")

        shop.is_active = not shop.is_active
        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(shop)
        return shop

