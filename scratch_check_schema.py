import asyncio
import os
import asyncpg
from dotenv import load_dotenv

async def main():
    load_dotenv()
    db_url = os.getenv("DATABASE_URL")
    if db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql+asyncpg://", "postgres://")
    conn = await asyncpg.connect(db_url)
    
    rows = await conn.fetch('''
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = 'menu_items';
    ''')
    for row in rows:
        print(f"{row['column_name']} ({row['data_type']}) - Nullable: {row['is_nullable']}")
    
    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
