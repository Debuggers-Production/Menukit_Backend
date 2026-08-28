import asyncio
import os
from sqlalchemy import text
from app.database.session import engine

async def main():
    async with engine.begin() as conn:
        try:
            print("Dropping unique constraint on user_id in shops...")
            # Usually named shops_user_id_key
            await conn.execute(text("ALTER TABLE shops DROP CONSTRAINT shops_user_id_key;"))
        except Exception as e:
            print("Could not drop constraint, maybe already dropped or differently named:", e)

if __name__ == "__main__":
    asyncio.run(main())
