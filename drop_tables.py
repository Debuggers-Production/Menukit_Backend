import asyncio
from sqlalchemy import text
from app.database.session import engine

async def drop_new_tables():
    async with engine.begin() as conn:
        # Need to drop FKs from shops, categories, discounts, menu_items if they were added
        # But create_all doesn't add columns to existing tables, so they don't have the FKs yet.
        await conn.execute(text("DROP TABLE IF EXISTS branch_item_overrides CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS menu_catalogs CASCADE"))
        print("Dropped tables")

if __name__ == "__main__":
    asyncio.run(drop_new_tables())
