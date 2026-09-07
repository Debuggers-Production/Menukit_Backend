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
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1;"))
            # Auto-migrate GST & Compliance columns if missing
            gst_migrations = [
                "ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS gst_enabled BOOLEAN DEFAULT FALSE;",
                "ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS gstin VARCHAR(50);",
                "ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS legal_name VARCHAR(255);",
                "ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS fssai_license VARCHAR(50);",
                "ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS cgst_rate FLOAT DEFAULT 2.5;",
                "ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS sgst_rate FLOAT DEFAULT 2.5;",
                "ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS inclusive_tax BOOLEAN DEFAULT FALSE;",
                "ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS tax_invoice_notes VARCHAR(500);",
            ]
            for stmt in gst_migrations:
                try:
                    await conn.execute(text(stmt))
                except Exception as mig_err:
                    print(f"Migration notice: {mig_err}")
    except Exception as e:
        print(f"Database startup info: {e}")


async def close_db():
    """Close database connections."""
    await engine.dispose()
