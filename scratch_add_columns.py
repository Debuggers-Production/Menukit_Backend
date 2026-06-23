import asyncio
from sqlalchemy import text
from app.database.session import async_session_factory

async def main():
    async with async_session_factory() as db:
        await db.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS category VARCHAR(100);"))
        await db.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS cuisine VARCHAR(255);"))
        await db.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS city VARCHAR(100);"))
        await db.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS area VARCHAR(100);"))
        await db.commit()
        print("Columns added successfully.")

if __name__ == "__main__":
    asyncio.run(main())
