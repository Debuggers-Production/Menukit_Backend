import asyncio
from sqlalchemy import select
from app.database.session import async_session_factory
from app.models.user import User

async def main():
    async with async_session_factory() as db:
        res = await db.execute(select(User).limit(5))
        users = res.scalars().all()
        print("Successfully queried users with relationships:", [u.email for u in users])

if __name__ == "__main__":
    asyncio.run(main())
