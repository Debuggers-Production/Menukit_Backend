import asyncio
from sqlalchemy import text
from app.database.session import engine

async def main():
    async with engine.begin() as conn:
        print("1. Creating menu_catalogs table if not exists...")
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS menu_catalogs (
                id UUID PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name VARCHAR(255) NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """))

        print("2. Creating branch_item_overrides table if not exists...")
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS branch_item_overrides (
                id UUID PRIMARY KEY,
                shop_id UUID NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
                menu_item_id UUID NOT NULL REFERENCES menu_items(id) ON DELETE CASCADE,
                override_price FLOAT,
                is_available BOOLEAN,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """))

        print("3. Adding menu_catalog_id column to shops, categories, discounts, menu_items...")
        for tbl in ['shops', 'categories', 'discounts', 'menu_items']:
            await conn.execute(text(f"""
                ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS menu_catalog_id UUID;
            """))

        print("4. Populating menu_catalogs for existing shops...")
        await conn.execute(text("""
            INSERT INTO menu_catalogs (id, user_id, name, created_at, updated_at)
            SELECT gen_random_uuid(), user_id, name || ' Menu', NOW(), NOW() 
            FROM shops
            WHERE NOT EXISTS (
                SELECT 1 FROM menu_catalogs mc WHERE mc.user_id = shops.user_id AND mc.name = shops.name || ' Menu'
            );
        """))

        print("5. Linking menu_catalog_id in shops...")
        await conn.execute(text("""
            UPDATE shops SET menu_catalog_id = mc.id
            FROM menu_catalogs mc 
            WHERE mc.name = shops.name || ' Menu' AND mc.user_id = shops.user_id AND shops.menu_catalog_id IS NULL;
        """))

        print("6. Linking menu_catalog_id in categories...")
        await conn.execute(text("""
            UPDATE categories SET menu_catalog_id = s.menu_catalog_id
            FROM shops s 
            WHERE categories.shop_id = s.id AND categories.menu_catalog_id IS NULL;
        """))

        print("7. Linking menu_catalog_id in menu_items...")
        await conn.execute(text("""
            UPDATE menu_items SET menu_catalog_id = s.menu_catalog_id
            FROM shops s 
            WHERE menu_items.shop_id = s.id AND menu_items.menu_catalog_id IS NULL;
        """))

        print("8. Linking menu_catalog_id in discounts...")
        await conn.execute(text("""
            UPDATE discounts SET menu_catalog_id = s.menu_catalog_id
            FROM shops s 
            WHERE discounts.shop_id = s.id AND discounts.menu_catalog_id IS NULL;
        """))

        print("Migration completed successfully!")

if __name__ == "__main__":
    asyncio.run(main())
