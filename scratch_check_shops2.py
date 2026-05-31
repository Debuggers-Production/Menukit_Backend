import asyncio
from sqlalchemy import text
from app.database.session import engine

async def check():
    async with engine.begin() as conn:
        res = await conn.execute(text("SELECT id, name, slug, logo_url, banner_url FROM shops"))
        shops = res.fetchall()
        for s in shops:
            print(s)

if __name__ == "__main__":
    asyncio.run(check())
