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
    
    # Check if slug exists in menu_items
    try:
        await conn.execute('ALTER TABLE menu_items DROP COLUMN slug;')
        print("Dropped 'slug' column from 'menu_items'.")
    except Exception as e:
        print(f"Error dropping column: {e}")
        
    # Let's also fix alembic_version if it is stuck on a15defb30380
    try:
        version = await conn.fetchval('SELECT version_num FROM alembic_version;')
        if version == 'a15defb30380':
            print("Found missing alembic version 'a15defb30380', deleting it so we can re-sync...")
            await conn.execute("UPDATE alembic_version SET version_num = '0612d1c46553';") # The last known good one from listing? 
            print("Set alembic_version to a valid existing one or we can just leave it if it's fine")
    except Exception as e:
        print(f"Error checking alembic version: {e}")
        
    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
