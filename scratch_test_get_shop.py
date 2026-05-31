import asyncio
import uuid
from app.database.session import async_session_factory
from app.services.shop_service import ShopService

async def main():
    shop_id_str = "a79d6762-a231-4527-818e-af78af7caa4f"
    shop_id = uuid.UUID(shop_id_str)
    async with async_session_factory() as db:
        service = ShopService(db)
        shop = await service.get_shop_by_id(shop_id)
        if shop:
            print(f"Found shop: {shop.name}")
        else:
            print("Shop not found via get_shop_by_id!")

if __name__ == "__main__":
    asyncio.run(main())
