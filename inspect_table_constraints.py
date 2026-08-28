import asyncio
from sqlalchemy import text
from app.database.session import async_session_factory

async def main():
    async with async_session_factory() as db:
        for tbl in ['menu_items', 'categories', 'discounts']:
            res = await db.execute(text(f"""
                SELECT column_name, is_nullable 
                FROM information_schema.columns 
                WHERE table_name='{tbl}';
            """))
            cols = res.fetchall()
            print(f"Table {tbl} columns:", cols)

if __name__ == "__main__":
    asyncio.run(main())
