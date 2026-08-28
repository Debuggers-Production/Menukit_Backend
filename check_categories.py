import asyncio
from sqlalchemy import text
from app.database.session import engine

async def check():
    async with engine.begin() as conn:
        res = await conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'categories'"))
        cols = [r[0] for r in res.fetchall()]
        print("Columns in categories:", cols)

if __name__ == "__main__":
    asyncio.run(check())
