import asyncio
from sqlalchemy import text
from app.database.session import async_session_factory

async def main():
    async with async_session_factory() as db:
        res = await db.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='shops';"))
        columns = [r[0] for r in res.fetchall()]
        print("Columns in shops table:", columns)

if __name__ == "__main__":
    asyncio.run(main())
