import asyncio
from app.database.session import engine
from sqlalchemy import text

async def add_col():
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS online_payments_enabled BOOLEAN DEFAULT TRUE NOT NULL;"))
        print("Column online_payments_enabled added successfully to shop_settings!")

if __name__ == "__main__":
    asyncio.run(add_col())
