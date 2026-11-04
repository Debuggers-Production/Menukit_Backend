import asyncio
import os
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))
os.chdir(backend_dir)

from dotenv import load_dotenv
load_dotenv(backend_dir / ".env")

from sqlalchemy import text
from app.database.session import engine, async_session_factory
from app.database.base import Base
import app.models  # Ensures all models are registered in Base.metadata

async def auto_migrate():
    print("Connecting to database to check for missing columns across all tables...")
    dialect = engine.dialect

    async with engine.begin() as conn:
        for table_name, table in Base.metadata.tables.items():
            res = await conn.execute(text(
                "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = :tname"
            ), {"tname": table_name})
            existing_cols = {r[0]: r[1] for r in res.fetchall()}
            
            if not existing_cols:
                print(f"[MISSING TABLE] {table_name} does not exist in DB!")
                continue

            for col in table.columns:
                if col.name not in existing_cols:
                    col_type = col.type.compile(dialect=dialect)
                    
                    # Handle defaults / nullability safely for existing data
                    # If nullable=False without a server_default, adding it directly would fail on existing rows.
                    # So we supply safe defaults or make it nullable / set default.
                    default_clause = ""
                    if col.server_default is not None:
                        # Extract server default text if possible
                        default_clause = f" DEFAULT {col.server_default.arg}"
                    elif col.default is not None and col.default.is_scalar:
                        val = col.default.arg
                        if isinstance(val, bool):
                            default_clause = f" DEFAULT {'TRUE' if val else 'FALSE'}"
                        elif isinstance(val, (int, float)):
                            default_clause = f" DEFAULT {val}"
                        elif isinstance(val, str):
                            default_clause = f" DEFAULT '{val}'"
                    elif not col.nullable:
                        # Provide reasonable default based on type
                        type_str = str(col_type).upper()
                        if "BOOL" in type_str:
                            default_clause = " DEFAULT FALSE"
                        elif "INT" in type_str or "FLOAT" in type_str or "NUMERIC" in type_str:
                            default_clause = " DEFAULT 0"
                        elif "JSON" in type_str:
                            default_clause = " DEFAULT '[]'::jsonb" if "[]" in str(col.default) else " DEFAULT '{}'::jsonb"
                        elif "VARCHAR" in type_str or "TEXT" in type_str:
                            default_clause = " DEFAULT ''"

                    null_clause = " NOT NULL" if (not col.nullable and default_clause) else ""
                    
                    sql = f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {col.name} {col_type}{default_clause}{null_clause};"
                    print(f"Adding column: {table_name}.{col.name} ({col_type}) -> {sql}")
                    try:
                        await conn.execute(text(sql))
                        print(f"  [OK] Successfully added {table_name}.{col.name}")
                    except Exception as e:
                        print(f"  [ERROR] Failed to add {table_name}.{col.name}: {e}")

        print("\nAll missing columns inspected and migrated!")

if __name__ == "__main__":
    asyncio.run(auto_migrate())
