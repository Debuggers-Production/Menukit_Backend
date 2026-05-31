import asyncio
from sqlalchemy import select
from app.database.session import SessionLocal
from app.models.shop import Shop
from app.models.menu_image import MenuImage

async def check_db():
    async with SessionLocal() as db:
        res = await db.execute(select(Shop.id, Shop.logo_url, Shop.banner_url))
        shops = res.fetchall()
        print("Shops:")
        for s in shops:
            print(s)
            
        res = await db.execute(select(MenuImage.id, MenuImage.image_url))
        images = res.fetchall()
        print("\nImages:")
        for img in images:
            print(img)

if __name__ == "__main__":
    asyncio.run(check_db())
