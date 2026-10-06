"""Async SQLAlchemy database session management."""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,

    pool_size=20,
    max_overflow=30,
    pool_recycle=1800,
    pool_pre_ping=True
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    """Dependency that provides an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Initialize database connection check."""
    from sqlalchemy import text
    import app.models  # noqa: F401

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1;"))
    except Exception as e:
        print(f"Database startup info: {e}")


async def init_chalkboard_table():
    """Ensure essential tables and newly introduced schema columns exist in database."""
    from sqlalchemy import text
    
    ddl_script = """
        -- 1. Chalkboards table
        CREATE TABLE IF NOT EXISTS chalkboards (
            id UUID PRIMARY KEY,
            shop_id UUID UNIQUE NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
            is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            title VARCHAR(100),
            message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE UNIQUE INDEX IF NOT EXISTS ix_chalkboards_shop_id ON chalkboards(shop_id);

        -- 2. Users table updates
        ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(20);
        ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_verified BOOLEAN NOT NULL DEFAULT FALSE;
        CREATE INDEX IF NOT EXISTS ix_users_phone ON users(phone);

        -- 2b. Shops table updates (allow multiple shops per user)
        ALTER TABLE shops DROP CONSTRAINT IF EXISTS shops_user_id_key;
        CREATE INDEX IF NOT EXISTS ix_shops_user_id ON shops(user_id);

        -- 3. Orders table updates
        ALTER TABLE orders ADD COLUMN IF NOT EXISTS daily_order_number INTEGER;
        ALTER TABLE orders ADD COLUMN IF NOT EXISTS whatsapp_sent BOOLEAN DEFAULT FALSE;
        ALTER TABLE orders ADD COLUMN IF NOT EXISTS razorpay_order_id VARCHAR(255);
        ALTER TABLE orders ADD COLUMN IF NOT EXISTS cashfree_order_id VARCHAR(255);
        ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_session_id VARCHAR(255);
        ALTER TABLE orders ADD COLUMN IF NOT EXISTS credits_rewarded BOOLEAN DEFAULT FALSE;
        ALTER TABLE orders ADD COLUMN IF NOT EXISTS settlement_status VARCHAR(50);
        ALTER TABLE orders ADD COLUMN IF NOT EXISTS settled_at TIMESTAMPTZ;
        ALTER TABLE orders ADD COLUMN IF NOT EXISTS razorpay_settlement_id VARCHAR(255);
        ALTER TABLE orders ADD COLUMN IF NOT EXISTS razorpay_transfer_id VARCHAR(255);
        ALTER TABLE orders ADD COLUMN IF NOT EXISTS refund_id VARCHAR(255);
        ALTER TABLE orders ADD COLUMN IF NOT EXISTS cancellation_reason VARCHAR(255);
        ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_expires_at TIMESTAMPTZ;
        ALTER TABLE orders ADD COLUMN IF NOT EXISTS applied_discount_ids JSONB;
        ALTER TABLE orders ADD COLUMN IF NOT EXISTS applied_discount_codes JSONB;
        ALTER TABLE orders ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;

        -- 3b. Order Items table updates
        ALTER TABLE order_items ADD COLUMN IF NOT EXISTS applied_discount_id UUID;
        ALTER TABLE order_items ADD COLUMN IF NOT EXISTS is_completed BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE order_items ADD COLUMN IF NOT EXISTS is_cancelled BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE order_items ADD COLUMN IF NOT EXISTS cancellation_reason VARCHAR(255);
        ALTER TABLE order_items ADD COLUMN IF NOT EXISTS variant_info JSONB;
        ALTER TABLE order_items ADD COLUMN IF NOT EXISTS addons_info JSONB;

        -- 4. Discounts table updates
        ALTER TABLE discounts ADD COLUMN IF NOT EXISTS code VARCHAR(50);
        ALTER TABLE discounts ADD COLUMN IF NOT EXISTS buy_quantity INTEGER;
        ALTER TABLE discounts ADD COLUMN IF NOT EXISTS get_quantity INTEGER;
        ALTER TABLE discounts ADD COLUMN IF NOT EXISTS reward_target_ids JSONB;
        ALTER TABLE discounts ADD COLUMN IF NOT EXISTS target_ids JSONB;
        ALTER TABLE discounts ADD COLUMN IF NOT EXISTS available_days JSONB;
        ALTER TABLE discounts ADD COLUMN IF NOT EXISTS available_time_presets JSONB;
        ALTER TABLE discounts ADD COLUMN IF NOT EXISTS visibility_type VARCHAR(50) NOT NULL DEFAULT 'everyone_unlock_members';
        ALTER TABLE discounts ADD COLUMN IF NOT EXISTS display_order INTEGER NOT NULL DEFAULT 0;

        -- 5. Customer discount codes table & column updates
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
        ALTER TABLE customer_discount_codes ADD COLUMN IF NOT EXISTS customer_id UUID REFERENCES customers(id) ON DELETE SET NULL;
        ALTER TABLE customer_discount_codes ADD COLUMN IF NOT EXISTS customer_identifier VARCHAR(100);
        ALTER TABLE customer_discount_codes ADD COLUMN IF NOT EXISTS code VARCHAR(100);
        ALTER TABLE customer_discount_codes ADD COLUMN IF NOT EXISTS is_redeemed BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE customer_discount_codes ADD COLUMN IF NOT EXISTS redeemed_at TIMESTAMPTZ;
        CREATE INDEX IF NOT EXISTS ix_customer_discount_codes_discount_id ON customer_discount_codes(discount_id);
        CREATE INDEX IF NOT EXISTS ix_customer_discount_codes_shop_id ON customer_discount_codes(shop_id);
        CREATE INDEX IF NOT EXISTS ix_customer_discount_codes_code ON customer_discount_codes(code);

        -- 6. Discount redemptions table & column updates
        CREATE TABLE IF NOT EXISTS discount_redemptions (
            id UUID PRIMARY KEY,
            discount_id UUID NOT NULL REFERENCES discounts(id) ON DELETE CASCADE,
            shop_id UUID NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
            code VARCHAR(100) NOT NULL,
            redeemed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            customer_identifier VARCHAR(100),
            redeemed_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
            order_id UUID REFERENCES orders(id) ON DELETE SET NULL,
            status VARCHAR(50) NOT NULL DEFAULT 'active',
            menu_item_id UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        ALTER TABLE discount_redemptions ADD COLUMN IF NOT EXISTS code VARCHAR(100);
        ALTER TABLE discount_redemptions ADD COLUMN IF NOT EXISTS redeemed_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
        ALTER TABLE discount_redemptions ADD COLUMN IF NOT EXISTS customer_identifier VARCHAR(100);
        ALTER TABLE discount_redemptions ADD COLUMN IF NOT EXISTS redeemed_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL;
        ALTER TABLE discount_redemptions ADD COLUMN IF NOT EXISTS order_id UUID REFERENCES orders(id) ON DELETE SET NULL;
        ALTER TABLE discount_redemptions ADD COLUMN IF NOT EXISTS status VARCHAR(50) NOT NULL DEFAULT 'active';
        ALTER TABLE discount_redemptions ADD COLUMN IF NOT EXISTS menu_item_id UUID;
        CREATE INDEX IF NOT EXISTS ix_discount_redemptions_discount_id ON discount_redemptions(discount_id);
        CREATE INDEX IF NOT EXISTS ix_discount_redemptions_shop_id ON discount_redemptions(shop_id);
        CREATE INDEX IF NOT EXISTS ix_discount_redemptions_code ON discount_redemptions(code);

        -- 7. Shop settings updates
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS max_delivery_distance FLOAT DEFAULT 0.0;
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS hide_discovery_badge BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS base_delivery_charge FLOAT NOT NULL DEFAULT 0.0;
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS base_delivery_distance FLOAT NOT NULL DEFAULT 0.0;
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS extra_delivery_distance_step FLOAT NOT NULL DEFAULT 1.0;
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS extra_delivery_charge_per_step FLOAT NOT NULL DEFAULT 0.0;
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS delivery_enabled BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS takeaway_enabled BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS dinein_enabled BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS dinein_tables_enabled BOOLEAN NOT NULL DEFAULT TRUE;
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS dinein_tables_count INTEGER NOT NULL DEFAULT 10;
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS auto_accept_orders BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS online_payments_enabled BOOLEAN NOT NULL DEFAULT TRUE;
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS online_payments_dinein_enabled BOOLEAN NOT NULL DEFAULT TRUE;
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS online_payments_takeaway_enabled BOOLEAN NOT NULL DEFAULT TRUE;
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS online_payments_delivery_enabled BOOLEAN NOT NULL DEFAULT TRUE;
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS accept_after_payment BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS razorpay_account_id VARCHAR(100);
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS razorpay_product_id VARCHAR(100);
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS razorpay_route_status VARCHAR(50);
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS gst_enabled BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS gstin VARCHAR(50);
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS legal_name VARCHAR(255);
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS fssai_license VARCHAR(50);
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS cgst_rate FLOAT NOT NULL DEFAULT 2.5;
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS sgst_rate FLOAT NOT NULL DEFAULT 2.5;
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS tax_invoice_notes VARCHAR(500);
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS return_allowed BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS return_window_days INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS return_policy_notes VARCHAR(500);
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS refund_allowed BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS refund_policy_notes VARCHAR(500);
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS replacement_allowed BOOLEAN NOT NULL DEFAULT TRUE;
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS replacement_window_days INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS replacement_policy_notes VARCHAR(500);
        ALTER TABLE order_items ALTER COLUMN menu_item_id DROP NOT NULL;

        -- 8. High-performance composite query indexes
        CREATE INDEX IF NOT EXISTS ix_orders_shop_created ON orders(shop_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS ix_orders_customer_phone ON orders(customer_phone);
        CREATE INDEX IF NOT EXISTS ix_orders_shop_status ON orders(shop_id, order_status);
        CREATE INDEX IF NOT EXISTS ix_order_items_order_id ON order_items(order_id);
        CREATE INDEX IF NOT EXISTS ix_order_items_menu_item_id ON order_items(menu_item_id);
        CREATE INDEX IF NOT EXISTS ix_menu_items_catalog_avail ON menu_items(menu_catalog_id, is_available);
        CREATE INDEX IF NOT EXISTS ix_menu_items_cat_display ON menu_items(category_id, display_order);
        CREATE INDEX IF NOT EXISTS ix_categories_catalog_active ON categories(menu_catalog_id, is_active, display_order);
        CREATE INDEX IF NOT EXISTS ix_discounts_catalog_active ON discounts(menu_catalog_id, is_active);
        CREATE INDEX IF NOT EXISTS ix_customer_codes_cust_ident ON customer_discount_codes(customer_identifier);
        CREATE INDEX IF NOT EXISTS ix_discount_redemptions_cust_ident ON discount_redemptions(customer_identifier);
        CREATE INDEX IF NOT EXISTS ix_discount_redemptions_shop_status ON discount_redemptions(shop_id, status);
    """

    try:
        async with engine.connect() as conn:
            raw = await conn.get_raw_connection()
            await raw.driver_connection.execute(ddl_script)
    except Exception as e:
        print(f"Database table initialization notice: {e}")


async def close_db():
    """Close database connections."""
    await engine.dispose()
