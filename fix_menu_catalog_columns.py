import asyncio
from sqlalchemy import text
from app.database.session import engine

async def main():
    async with engine.begin() as conn:
        print("1. Updating menu_catalog_id for any null rows...")
        await conn.execute(text("""
            UPDATE categories SET menu_catalog_id = s.menu_catalog_id
            FROM shops s WHERE categories.shop_id = s.id AND categories.menu_catalog_id IS NULL;
        """))
        await conn.execute(text("""
            UPDATE menu_items SET menu_catalog_id = s.menu_catalog_id
            FROM shops s WHERE menu_items.shop_id = s.id AND menu_items.menu_catalog_id IS NULL;
        """))
        await conn.execute(text("""
            UPDATE discounts SET menu_catalog_id = s.menu_catalog_id
            FROM shops s WHERE discounts.shop_id = s.id AND discounts.menu_catalog_id IS NULL;
        """))

        print("2. Making shop_id nullable in menu_items, categories, discounts...")
        for tbl in ['menu_items', 'categories', 'discounts']:
            await conn.execute(text(f"ALTER TABLE {tbl} ALTER COLUMN shop_id DROP NOT NULL;"))

        print("3. Making menu_catalog_id NOT NULL in menu_items, categories, discounts...")
        for tbl in ['menu_items', 'categories', 'discounts']:
            await conn.execute(text(f"ALTER TABLE {tbl} ALTER COLUMN menu_catalog_id SET NOT NULL;"))

        print("Column constraints updated successfully!")

if __name__ == "__main__":
    asyncio.run(main())
