import asyncio
from sqlalchemy import text
from app.database.session import engine

async def fix_slug():
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE shops SET slug = 'test-hotel' WHERE id = 'a79d6762-a231-4527-818e-af78af7caa4f'"))
        print("Restored slug to test-hotel")

if __name__ == "__main__":
    asyncio.run(fix_slug())
