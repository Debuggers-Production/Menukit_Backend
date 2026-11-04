import asyncio
import os
import sys
from pathlib import Path

# Set up paths
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))
os.chdir(backend_dir)

from dotenv import load_dotenv
load_dotenv(backend_dir / ".env")

from sqlalchemy import text
from app.database.session import engine

async def run_migration():
    print(f"Connecting to database with engine...")
    async with engine.begin() as conn:
        print("Executing ALTER TABLE for shops...")
        await conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE;"))
        await conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;"))
        await conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS broadcast_credits INTEGER NOT NULL DEFAULT 0;"))
        await conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS google_review_link TEXT;"))
        await conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS review_widget_code TEXT;"))
        await conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS welcome_message TEXT;"))
        await conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS latitude FLOAT;"))
        await conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS longitude FLOAT;"))
        await conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS category VARCHAR(100);"))
        await conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS cuisine VARCHAR(255);"))
        await conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS city VARCHAR(100);"))
        await conn.execute(text("ALTER TABLE shops ADD COLUMN IF NOT EXISTS area VARCHAR(100);"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_shops_is_deleted ON shops(is_deleted);"))
        print("Shops table migration completed successfully!")

if __name__ == "__main__":
    asyncio.run(run_migration())

