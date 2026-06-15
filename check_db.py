import asyncio
from sqlalchemy import inspect
from app.database.session import engine

async def check():
    async with engine.connect() as conn:
        def get_tables(sync_conn):
            return inspect(sync_conn).get_table_names()
        tables = await conn.run_sync(get_tables)
        print("DB Tables:", tables)

asyncio.run(check())
