import asyncio
from app.services.image_scraper_service import ImageScraperService

async def main():
    scraper = ImageScraperService()
    urls = await scraper._search_bing("pizza")
    print(f"Found {len(urls)} urls")
    for url in urls[:3]:
        print(f"Testing URL: {url}")
        res = await scraper.download_image_url(url)
        if res:
            print("Download successful:", len(res[0]), "bytes", res[1])
        else:
            print("Download failed")

asyncio.run(main())
