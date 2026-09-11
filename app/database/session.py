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
    """Ensure chalkboards table exists in database."""
    from sqlalchemy import text
    try:
        async with engine.begin() as conn:
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS chalkboards (
                    id UUID PRIMARY KEY,
                    shop_id UUID UNIQUE NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
                    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    message TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE UNIQUE INDEX IF NOT EXISTS ix_chalkboards_shop_id ON chalkboards(shop_id);
            """))
    except Exception as e:
        print(f"Chalkboard table initialization notice: {e}")


async def close_db():
    """Close database connections."""
    await engine.dispose()
