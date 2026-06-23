import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

async def run():
    url = os.getenv('DATABASE_URL').replace('postgresql+asyncpg', 'postgresql')
    conn = await asyncpg.connect(url)
    await conn.execute("ALTER TABLE theme_settings ADD COLUMN IF NOT EXISTS border_radius VARCHAR(20) DEFAULT 'smooth' NOT NULL;")
    print("Column added")
    await conn.close()

if __name__ == '__main__':
    asyncio.run(run())
