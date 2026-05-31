import asyncio
from app.database.session import async_session_factory
from app.services.shop_service import ShopService
from app.models.shop import Shop
from sqlalchemy import select

async def test_update_shop():
    async with async_session_factory() as db:
        service = ShopService(db)
        res = await db.execute(select(Shop.user_id).where(Shop.id == 'a79d6762-a231-4527-818e-af78af7caa4f'))
        user_id = res.scalar_one()
        
        try:
            shop = await service.update_shop(user_id, {
                "name": "TEST-HOTEL",
                "description": "",
                "welcome_message": "",
                "logo_url": "http://test-url-2",
                "banner_url": ""
            })
            print(f"Updated logo_url to {shop.logo_url}")
            print(f"Updated slug to {shop.slug}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_update_shop())
