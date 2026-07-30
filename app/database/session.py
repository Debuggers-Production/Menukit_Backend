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
    """Initialize database (create tables)."""
    from app.database.base import Base
    from sqlalchemy import text
    # Import all models to register them
    import app.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        try:
            await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS credits_rewarded BOOLEAN DEFAULT FALSE;"))
            await conn.execute(text("ALTER TABLE contest_credits ALTER COLUMN credits TYPE DOUBLE PRECISION USING credits::double precision;"))
        except Exception as e:
            print(f"Auto-migration info: {e}")


async def close_db():
    """Close database connections."""
    await engine.dispose()
