import asyncio
from decimal import Decimal
from sqlalchemy import select
from app.database.session import async_session_factory
from app.models.shop import Shop
from app.models.category import Category
from app.services.menu_service import MenuService

async def main():
    async with async_session_factory() as db:
        shop_res = await db.execute(select(Shop).limit(1))
        shop = shop_res.scalar_one_or_none()
        if not shop:
            print("No shop found to test")
            return

        cat_res = await db.execute(select(Category).where(Category.menu_catalog_id == shop.menu_catalog_id).limit(1))
        cat = cat_res.scalar_one_or_none()
        if not cat:
            print("No category found to test")
            return

        service = MenuService(db)
        data = {
            "category_id": str(cat.id),
            "name": "Test Item Verification",
            "description": "Verification item test",
            "price": 120.00,
            "food_types": ["veg"],
        }
        item = await service.create_menu_item(shop.id, shop.user_id, data)
        print("Successfully created menu item:", item.id, item.name)

if __name__ == "__main__":
    asyncio.run(main())
