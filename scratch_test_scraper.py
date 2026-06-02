"""Test full image pipeline with Pixabay key."""
import asyncio
import sys
sys.path.insert(0, '.')

async def test():
    from app.services.image_scraper_service import ImageScraperService
    from app.core.config import get_settings
    
    settings = get_settings()
    print(f"Pixabay key configured: {'YES (' + settings.PIXABAY_API_KEY[:8] + '...)' if settings.PIXABAY_API_KEY else 'NO'}")
    
    scraper = ImageScraperService()
    
    print("\nTest 1: Pixabay search for 'Paneer Butter Masala'...")
    result = await scraper._try_pixabay("Paneer Butter Masala")
    print(f"  -> {'OK (' + str(len(result[0])) + ' bytes, ' + result[1] + ')' if result else 'FAILED'}")
    
    print("\nTest 2: Full fetch for 'Chicken Biryani'...")
    result2 = await scraper.fetch_food_image("Chicken Biryani")
    print(f"  -> {'OK (' + str(len(result2[0])) + ' bytes)' if result2 else 'FAILED'}")

    print("\nTest 3: Picsum fallback (no key)...")
    result3 = await scraper._try_picsum("Masala Dosa")
    print(f"  -> {'OK (' + str(len(result3[0])) + ' bytes)' if result3 else 'FAILED'}")

asyncio.run(test())
