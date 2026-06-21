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
        SELECT name, count(*) as c 
        FROM categories 
        GROUP BY name 
        HAVING count(*) > 1;
    ''')
    print("Duplicate Categories:")
    for row in rows:
        print(f"{row['name']}: {row['c']}")
        
    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
