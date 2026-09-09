import asyncio
from sqlalchemy import text
from app.database.session import engine

async def main():
    print("Connecting to production database...")
    async with engine.begin() as conn:
        print("1. Adding hide_discovery_badge to shop_settings if not exists...")
        await conn.execute(text("""
            ALTER TABLE shop_settings 
            ADD COLUMN IF NOT EXISTS hide_discovery_badge BOOLEAN NOT NULL DEFAULT FALSE;
        """))

        print("2. Creating customer_discount_codes table if not exists...")
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS customer_discount_codes (
                id UUID PRIMARY KEY,
                discount_id UUID NOT NULL REFERENCES discounts(id) ON DELETE CASCADE,
                shop_id UUID NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
                customer_id UUID REFERENCES customers(id) ON DELETE SET NULL,
                customer_identifier VARCHAR(100) NOT NULL,
                code VARCHAR(100) NOT NULL,
                is_redeemed BOOLEAN NOT NULL DEFAULT FALSE,
                redeemed_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """))

        print("3. Creating indices for customer_discount_codes...")
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_customer_discount_codes_discount_id ON customer_discount_codes(discount_id);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_customer_discount_codes_shop_id ON customer_discount_codes(shop_id);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_customer_discount_codes_customer_id ON customer_discount_codes(customer_id);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_customer_discount_codes_customer_identifier ON customer_discount_codes(customer_identifier);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_customer_discount_codes_code ON customer_discount_codes(code);"))

        print("4. Updating alembic_version...")
        res = await conn.execute(text("SELECT version_num FROM alembic_version"))
        curr = res.scalar()
        if curr:
            await conn.execute(text("UPDATE alembic_version SET version_num = 'e1f2a3b4c5d6'"))
            print(f"Updated alembic_version from '{curr}' to 'e1f2a3b4c5d6'.")
        else:
            await conn.execute(text("INSERT INTO alembic_version (version_num) VALUES ('e1f2a3b4c5d6')"))
            print("Inserted 'e1f2a3b4c5d6' into alembic_version.")

        print("\nMigration completed successfully without errors!")

if __name__ == "__main__":
    asyncio.run(main())
