"""SEO and dynamic Sitemap generation module."""

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone

from app.database.session import get_db
from app.models.shop import Shop
from app.core.config import get_settings

seo_router = APIRouter()

# Explicit documentation and user guide URLs
EXPLICIT_DOCS_GUIDES = [
    "https://debuggerstechnologies.com/menukit/docs/digital-catalog-guide",
    "https://debuggerstechnologies.com/menukit/docs/thermal-pos-printing-guide",
    "https://debuggerstechnologies.com/menukit/docs/multi-station-dispatch-guide",
    "https://debuggerstechnologies.com/menukit/docs/festive-schemes-discount-guide",
    "https://debuggerstechnologies.com/menukit/docs/store-discovery-guide",
    "https://debuggerstechnologies.com/menukit/docs/multilingual-billing-guide",
]

DOCS_PATHS = [
    "/docs",
    "/docs/digital-catalog-guide",
    "/docs/thermal-pos-printing-guide",
    "/docs/multi-station-dispatch-guide",
    "/docs/festive-schemes-discount-guide",
    "/docs/store-discovery-guide",
    "/docs/multilingual-billing-guide",
    "/docs/restaurant-customer-experience",
    "/docs/qr-menu-benefits",
]


@seo_router.get("/sitemap.xml", response_class=Response)
async def get_sitemap(db: AsyncSession = Depends(get_db)):
    """Generate dynamic XML sitemap for Google SEO with direct public slug shop routes and explicit documentation guides."""
    settings = get_settings()
    base_url = settings.effective_sitemap_base_url
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Static high-value routes
    static_routes = [
        {"path": "/", "changefreq": "daily", "priority": "1.0"},
        {"path": "/explore", "changefreq": "daily", "priority": "0.9"},
        {"path": "/terms", "changefreq": "monthly", "priority": "0.5"},
        {"path": "/privacy", "changefreq": "monthly", "priority": "0.5"},
        {"path": "/refund-policy", "changefreq": "monthly", "priority": "0.5"},
    ]

    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]

    # Add static routes
    for r in static_routes:
        xml_lines.append(f"""  <url>
    <loc>{base_url}{r["path"]}</loc>
    <lastmod>{today_iso}</lastmod>
    <changefreq>{r["changefreq"]}</changefreq>
    <priority>{r["priority"]}</priority>
  </url>""")

    # Add documentation guide routes relative to base_url
    for doc_path in DOCS_PATHS:
        xml_lines.append(f"""  <url>
    <loc>{base_url}{doc_path}</loc>
    <lastmod>{today_iso}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.7</priority>
  </url>""")

    # Add explicit canonical documentation guides
    for guide_url in EXPLICIT_DOCS_GUIDES:
        # Avoid duplicate if base_url already matches
        guide_relative = guide_url.replace("https://debuggerstechnologies.com/menukit", "")
        if not base_url.startswith("https://debuggerstechnologies.com/menukit"):
            xml_lines.append(f"""  <url>
    <loc>{guide_url}</loc>
    <lastmod>{today_iso}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>""")

    # Fetch active, non-deleted shops
    stmt = select(Shop.id, Shop.slug, Shop.updated_at).where(
        Shop.is_active == True,
        Shop.is_deleted == False
    )
    res = await db.execute(stmt)
    shops = res.all()

    # Add dynamic shop routes using direct public slug calling (/shop/{slug})
    for shop_id, slug, updated_at in shops:
        identifier = slug.strip() if slug and slug.strip() else str(shop_id)
        lastmod = updated_at.strftime("%Y-%m-%d") if updated_at else today_iso

        # Direct public storefront URL
        xml_lines.append(f"""  <url>
    <loc>{base_url}/shop/{identifier}</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>daily</changefreq>
    <priority>0.9</priority>
  </url>""")

        # Public schemes / savings fund URL
        xml_lines.append(f"""  <url>
    <loc>{base_url}/shop/{identifier}/schemes</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>""")

    xml_lines.append("</urlset>")
    xml_content = "\n".join(xml_lines)

    return Response(
        content=xml_content,
        media_type="application/xml",
        headers={
            "Cache-Control": "public, max-age=3600, stale-while-revalidate=86400"
        }
    )
