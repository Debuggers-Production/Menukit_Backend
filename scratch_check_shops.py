import asyncio
from sqlalchemy import select
from app.database.session import SessionLocal
from app.models.shop import Shop

async def main():
    async with SessionLocal() as db:
        res = await db.execute(select(Shop))
        shops = res.scalars().all()
        for s in shops:
            print(s.id, s.name, s.is_active)

if __name__ == "__main__":
    asyncio.run(main())
