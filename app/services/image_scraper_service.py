"""Image Scraper Service - fetches food images from the web."""

import httpx
import logging
import urllib.parse
from typing import Optional, Tuple

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
}


class ImageScraperService:
    """
    Fetches food images from public image APIs.

    Priority order:
      1. Pixabay API (free, 2500 req/day) — if PIXABAY_API_KEY is set
      2. Picsum Photos (deterministic placeholder, always works)
    """

    async def fetch_food_image(self, item_name: str) -> Optional[Tuple[bytes, str]]:
        """
        Fetch a food image for the given item name.
        Returns (image_bytes, mime_type) or None.
        """
        query = item_name.strip()
        logger.info(f"[ImageScraper] Searching image for: {query}")

        # --- Source 1: Pixabay API (requires free key) ---
        if settings.PIXABAY_API_KEY:
            result = await self._try_pixabay(query)
            if result:
                logger.info(f"[ImageScraper] Got image from Pixabay for: {query}")
                return result

        # --- Source 2: Picsum Photos (guaranteed fallback) ---
        result = await self._try_picsum(query)
        if result:
            logger.info(f"[ImageScraper] Used Picsum fallback for: {query}")
            return result

        logger.warning(f"[ImageScraper] All sources failed for: {query}")
        return None

    async def _try_pixabay(self, query: str) -> Optional[Tuple[bytes, str]]:
        """
        Query Pixabay image search API.
        Free tier: 2500 requests/day. Get key at https://pixabay.com/api/docs/
        """
        encoded = urllib.parse.quote(f"{query} food")
        api_url = (
            f"https://pixabay.com/api/"
            f"?key={settings.PIXABAY_API_KEY}"
            f"&q={encoded}"
            f"&image_type=photo"
            f"&category=food"
            f"&min_width=400"
            f"&min_height=400"
            f"&safesearch=true"
            f"&per_page=5"
            f"&order=popular"
        )

        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=10.0,
            ) as client:
                resp = await client.get(api_url)
                if resp.status_code != 200:
                    logger.debug(f"[Pixabay] API returned {resp.status_code}")
                    return None

                data = resp.json()
                hits = data.get("hits", [])

                if not hits:
                    # Retry without the food category filter (broader search)
                    api_url_broad = api_url.replace("&category=food", "")
                    resp2 = await client.get(api_url_broad)
                    if resp2.status_code == 200:
                        hits = resp2.json().get("hits", [])

                for hit in hits:
                    image_url = hit.get("largeImageURL") or hit.get("webformatURL")
                    if not image_url:
                        continue
                    try:
                        img_resp = await client.get(image_url, timeout=10.0, headers=HEADERS)
                        if img_resp.status_code == 200 and len(img_resp.content) > 5000:
                            content_type = img_resp.headers.get("content-type", "image/jpeg").split(";")[0]
                            if "image" in content_type and "svg" not in content_type:
                                return img_resp.content, content_type
                    except Exception:
                        continue

        except Exception as e:
            logger.debug(f"[Pixabay] Failed for '{query}': {e}")

        return None

    async def _try_picsum(self, query: str) -> Optional[Tuple[bytes, str]]:
        """
        Picsum Photos fallback — deterministic, always works.
        Same item name → same photo every time (hash-based seed).
        Note: these are generic random photos, not food-specific.
        """
        seed = abs(hash(query)) % 1000
        url = f"https://picsum.photos/seed/{seed}/800/600"

        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=10.0,
                headers=HEADERS,
            ) as client:
                response = await client.get(url)
                if response.status_code == 200 and len(response.content) > 1000:
                    return response.content, "image/jpeg"
        except Exception as e:
            logger.debug(f"[Picsum] Failed: {e}")

        return None
