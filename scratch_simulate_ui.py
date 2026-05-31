import asyncio
from app.database.session import async_session_factory
from app.services.shop_service import ShopService
from app.models.shop import Shop
from sqlalchemy import select

async def simulate_ui():
    async with async_session_factory() as db:
        service = ShopService(db)
        
        # 1. Get the shop (simulate user loading the page)
        res = await db.execute(select(Shop).where(Shop.id == 'a79d6762-a231-4527-818e-af78af7caa4f'))
        shop = res.scalar_one()
        user_id = shop.user_id
        
        print(f"Original Logo: {shop.logo_url}")
        
        # 2. Simulate Upload (new URL generated)
        new_url = "http://89.167.72.254:9000/menuproductimages/logos/new-fake-uuid.jpg"
        
        # 3. Simulate UI sending PUT request with current formData + new URL
        form_data = {
            "name": shop.name,
            "description": shop.description,
            "welcome_message": shop.welcome_message,
            "logo_url": new_url,
            "banner_url": shop.banner_url,
            "phone": shop.phone,
            "whatsapp": shop.whatsapp,
            "address": shop.address
        }
        
        try:
            updated_shop = await service.update_shop(user_id, form_data)
            print(f"Updated Logo: {updated_shop.logo_url}")
        except Exception as e:
            print(f"Error during update: {e}")

if __name__ == "__main__":
    asyncio.run(simulate_ui())
