import asyncio
import logging
from sqlalchemy import text
from app.database.session import engine

async def migrate_urls():
    async with engine.begin() as conn:
        print("Migrating Shop logos...")
        await conn.execute(text("UPDATE shops SET logo_url = REPLACE(logo_url, '/uploads/', 'http://89.167.72.254:9000/menuproductimages/') WHERE logo_url LIKE '/uploads/%'"))

        print("Migrating Shop banners...")
        await conn.execute(text("UPDATE shops SET banner_url = REPLACE(banner_url, '/uploads/', 'http://89.167.72.254:9000/menuproductimages/') WHERE banner_url LIKE '/uploads/%'"))

        print("Migrating MenuImages image_url...")
        await conn.execute(text("UPDATE menu_images SET image_url = REPLACE(image_url, '/uploads/', 'http://89.167.72.254:9000/menuproductimages/') WHERE image_url LIKE '/uploads/%'"))

        print("Migrating MenuImages thumbnail_url...")
        await conn.execute(text("UPDATE menu_images SET thumbnail_url = REPLACE(thumbnail_url, '/uploads/', 'http://89.167.72.254:9000/menuproductimages/') WHERE thumbnail_url LIKE '/uploads/%'"))

        print("Done!")

if __name__ == "__main__":
    asyncio.run(migrate_urls())
