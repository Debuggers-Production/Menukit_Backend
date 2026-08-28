import asyncio
import os
from sqlalchemy import text
from app.database.session import engine

async def main():
    async with engine.begin() as conn:
        try:
            print("Adding user_id column...")
            await conn.execute(text("ALTER TABLE qr_codes ADD COLUMN user_id UUID REFERENCES users(id) ON DELETE CASCADE;"))
        except Exception as e:
            print("Could not add column, maybe already exists:", e)
            
        try:
            print("Populating user_id...")
            await conn.execute(text("UPDATE qr_codes SET user_id = shops.user_id FROM shops WHERE qr_codes.shop_id = shops.id;"))
        except Exception as e:
            print("Error populating:", e)
            
        try:
            print("Dropping shop_id...")
            await conn.execute(text("ALTER TABLE qr_codes DROP COLUMN shop_id;"))
        except Exception as e:
            print("Error dropping:", e)

if __name__ == "__main__":
    asyncio.run(main())
