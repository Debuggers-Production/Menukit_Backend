from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from app.database.session import get_db
from app.models.shop import Shop
from datetime import datetime
from app.core.config import get_settings
SETTINGS=get_settings()
seo_router = APIRouter()

@seo_router.get("/sitemap.xml", response_class=Response)
async def get_sitemap(db: AsyncSession = Depends(get_db)):
    """Generate dynamic sitemap for Google SEO."""
    
    # Base URLs
    base_url = SETTINGS.SEO_FRONTEND_URL
    static_urls = [
        "/",
        "/explore",
        "/docs",
        "/docs/restaurant-customer-experience",
        "/docs/qr-menu-benefits"
    ]
    
    # Build XML
    xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_content += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    
    # Add static routes
    for url in static_urls:
        xml_content += f"""  <url>
    <loc>{base_url}{url}</loc>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>\n"""

    # Fetch active shops
    result = await db.execute(select(Shop.slug).where(Shop.is_active == True))
    slugs = result.scalars().all()
    
    # Add dynamic shop routes
    for slug in slugs:
        xml_content += f"""  <url>
    <loc>{base_url}/store/{slug}</loc>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>\n"""

    xml_content += '</urlset>'
    
    return Response(content=xml_content, media_type="application/xml")
