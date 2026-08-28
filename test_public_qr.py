import asyncio
from sqlalchemy import select
from app.database.session import async_session_factory
from app.models.shop import Shop
from app.models.qr_code import QRCode

async def main():
    async with async_session_factory() as db:
        shop_res = await db.execute(select(Shop).limit(1))
        shop = shop_res.scalar_one_or_none()
        if shop:
            qr_res = await db.execute(select(QRCode).where(QRCode.user_id == shop.user_id))
            qr = qr_res.scalar_one_or_none()
            print(f"Successfully retrieved QR code for shop {shop.id} (user {shop.user_id}):", qr.qr_url if qr else "None")

if __name__ == "__main__":
    asyncio.run(main())
