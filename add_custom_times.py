import asyncio
from sqlalchemy import text
from app.database.session import engine

async def main():
    async with engine.begin() as conn:
        try:
            await conn.execute(text('ALTER TABLE menu_items ADD COLUMN custom_time_from VARCHAR(5);'))
            print('Added custom_time_from')
        except Exception as e:
            print(f"Error adding custom_time_from: {e}")
            
        try:
            await conn.execute(text('ALTER TABLE menu_items ADD COLUMN custom_time_to VARCHAR(5);'))
            print('Added custom_time_to')
        except Exception as e:
            print(f"Error adding custom_time_to: {e}")

if __name__ == "__main__":
    asyncio.run(main())
