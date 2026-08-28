import asyncio
from app.database.session import AsyncSessionLocal
from app.services.menu_service import MenuService
from app.api.v1.categories import _category_response

async def main():
    async with AsyncSessionLocal() as db:
        service = MenuService(db)
        from sqlalchemy import select
        from app.models.shop import Shop
        result = await db.execute(select(Shop))
        shop = result.scalars().first()
        if not shop:
            print("No shop found")
            return
        
        categories = await service.get_categories(shop.id, 0, 100)
        for cat in categories:
            resp = _category_response(cat)
            print(f"Cat: {resp.name}, count: {resp.item_count}")

asyncio.run(main())
