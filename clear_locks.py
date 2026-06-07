import asyncio
from sqlalchemy import text
from app.database.session import engine

async def main():
    async with engine.begin() as conn:
        res = await conn.execute(text('''
            SELECT pid, usename, state, query, wait_event_type, wait_event
            FROM pg_stat_activity
            WHERE state = 'idle in transaction' OR wait_event_type = 'Lock';
        '''))
        rows = res.fetchall()
        if not rows:
            print("No locks or idle transactions found.")
        for row in rows:
            print(dict(row._mapping))
            # Kill the process
            if row.pid != await conn.scalar(text('SELECT pg_backend_pid()')):
                await conn.execute(text(f'SELECT pg_terminate_backend({row.pid})'))
                print(f"Terminated pid {row.pid}")

if __name__ == "__main__":
    asyncio.run(main())
