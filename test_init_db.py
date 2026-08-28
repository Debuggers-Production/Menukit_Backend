import asyncio
from app.database.session import init_db

async def main():
    print("Testing init_db connection check...")
    await init_db()
    print("init_db completed successfully and quickly!")

if __name__ == "__main__":
    asyncio.run(main())
