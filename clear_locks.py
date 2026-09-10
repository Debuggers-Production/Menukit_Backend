import asyncio
import asyncpg
from app.core.config import get_settings

async def main():
    settings = get_settings()
    # convert postgresql+asyncpg:// to postgresql://
    db_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    
    print(f"Connecting to DB...")
    conn = await asyncpg.connect(db_url, timeout=10)
    
    print("Finding all active/idle connections to terminate...")
    rows = await conn.fetch('''
        SELECT pid, state, wait_event_type, wait_event, query 
        FROM pg_stat_activity 
        WHERE datname = current_database() 
          AND pid != pg_backend_pid();
    ''')
    
    print(f"Found {len(rows)} connections.")
    terminated = 0
    for r in rows:
        pid = r['pid']
        state = r['state']
        q = (r['query'] or '').strip().replace('\n', ' ')[:80]
        print(f"Terminating PID {pid} [{state}]: {q}")
        await conn.execute(f"SELECT pg_terminate_backend({pid});")
        terminated += 1
        
    print(f"\nSuccessfully terminated {terminated} lingering connections and released all locks.")
    
    # Check current status
    remaining = await conn.fetchval('''
        SELECT count(*) FROM pg_stat_activity 
        WHERE datname = current_database() AND pid != pg_backend_pid();
    ''')
    print(f"Remaining active connections: {remaining}")
    
    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
