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
    
    # Deduplicate menu items first
    print("Deduplicating menu items...")
    item_rows = await conn.fetch("SELECT min(name) as name, category_id, array_agg(id) as ids FROM menu_items GROUP BY shop_id, category_id, lower(name) HAVING count(*) > 1;")
    for row in item_rows:
        ids = row['ids']
        winner_id = ids[0]
        loser_ids = ids[1:]
        print(f"Item '{row['name']}': keeping {winner_id}, removing {loser_ids}")
        
        # delete losers
        await conn.execute("DELETE FROM menu_items WHERE id = ANY($1)", loser_ids)

    # Deduplicate categories
    print("Deduplicating categories...")
    cat_rows = await conn.fetch("SELECT min(name) as name, array_agg(id) as ids FROM categories GROUP BY shop_id, lower(name) HAVING count(*) > 1;")
    for row in cat_rows:
        ids = row['ids']
        winner_id = ids[0]
        loser_ids = ids[1:]
        print(f"Category '{row['name']}': keeping {winner_id}, removing {loser_ids}")
        
        # reassign menu items from losers to winner
        for loser_id in loser_ids:
            await conn.execute("UPDATE menu_items SET category_id = $1 WHERE category_id = $2", winner_id, loser_id)
            
        # delete losers
        await conn.execute("DELETE FROM categories WHERE id = ANY($1)", loser_ids)

    print("Deduplication complete!")
    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
