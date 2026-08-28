import asyncio
from app.database.session import engine
from app.database.base import Base
from app.models.employee import Employee
from app.models.shop import Shop
from app.models.user import User

async def create_table():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[Employee.__table__])
    print("Table 'employees' created successfully.")

if __name__ == "__main__":
    asyncio.run(create_table())
