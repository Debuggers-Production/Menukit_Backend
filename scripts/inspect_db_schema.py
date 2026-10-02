import asyncio
from sqlalchemy import text
from app.database.session import async_session_factory
from app.database.base import Base
import app.models

async def inspect_schema():
    async with async_session_factory() as db:
        for table_name, table in Base.metadata.tables.items():
            res = await db.execute(text(
                f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = :tname"
            ), {"tname": table_name})
            existing_cols = {r[0]: r[1] for r in res.fetchall()}
            if not existing_cols:
                print(f"[MISSING TABLE] {table_name}")
                continue
            
            missing_cols = []
            for col in table.columns:
                if col.name not in existing_cols:
                    missing_cols.append(col.name)
            
            if missing_cols:
                print(f"[TABLE: {table_name}] Missing columns: {missing_cols}")
            else:
                print(f"[TABLE: {table_name}] All {len(table.columns)} columns OK")

if __name__ == "__main__":
    asyncio.run(inspect_schema())
