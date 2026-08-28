import asyncio
from sqlalchemy import select
from app.database.session import async_session_factory
from app.models.shop import Shop
from app.services.discount_service import DiscountService

async def main():
    async with async_session_factory() as db:
        shop_res = await db.execute(select(Shop).limit(1))
        shop = shop_res.scalar_one_or_none()
        if not shop:
            print("No shop found")
            return
        
        service = DiscountService(db)
        discounts = await service.get_discounts(shop.id)
        print(f"DiscountService.get_discounts returned {len(discounts)} discounts for shop {shop.id}")

if __name__ == "__main__":
    asyncio.run(main())
