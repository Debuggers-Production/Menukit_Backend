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
      2. Wikipedia API (free, high quality images for named entities)
      3. Picsum Photos (deterministic placeholder, always works)
    """

    async def fetch_food_image(self, item_name: str) -> Optional[Tuple[bytes, str]]:
        """
        Fetch a food image for the given item name.
        Returns (image_bytes, mime_type) or None.
        """
        query = item_name.strip()
        logger.info(f"[ImageScraper] Searching image for: {query}")

        # --- Source 1: Pixabay API (requires free key) ---
        if getattr(settings, "PIXABAY_API_KEY", None):
            result = await self._try_pixabay(query)
            if result:
                logger.info(f"[ImageScraper] Got image from Pixabay for: {query}")
                return result

        # --- Source 2: Wikipedia API (high quality, specific) ---
        wiki_urls = await self._search_wikipedia(query)
        for url in wiki_urls:
            result = await self.download_image_url(url)
            if result:
                logger.info(f"[ImageScraper] Got image from Wikipedia for: {query}")
                return result

        # --- Source 3: Picsum Photos (guaranteed fallback) ---
        result = await self._try_picsum(query)
        if result:
            logger.info(f"[ImageScraper] Used Picsum fallback for: {query}")
            return result

        logger.warning(f"[ImageScraper] All sources failed for: {query}")
        return None

    async def search_image_urls(self, item_name: str, limit: int = 4) -> list[str]:
        """
        Search for food images and return a list of URLs (without downloading).
        """
        query = item_name.strip()
        logger.info(f"[ImageScraper] Searching image URLs for: {query}")
        urls = []

        if getattr(settings, "PIXABAY_API_KEY", None):
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
                f"&per_page=20"
                f"&order=popular"
            )
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(api_url)
                    if resp.status_code == 200:
                        hits = resp.json().get("hits", [])
                        if not hits:
                            # Retry broad search
                            api_url_broad = api_url.replace("&category=food", "")
                            resp2 = await client.get(api_url_broad)
                            if resp2.status_code == 200:
                                hits = resp2.json().get("hits", [])
                        
                        for hit in hits:
                            img_url = hit.get("largeImageURL") or hit.get("webformatURL")
                            if img_url and img_url not in urls:
                                urls.append(img_url)
            except Exception as e:
                logger.error(f"[Pixabay] Failed to fetch variants: {e}")

        # Fallback to Wikipedia if Pixabay fails or isn't set
        if not urls:
            urls = await self._search_wikipedia(query)

        # Fallback to multiple random picsum if all else fails
        if not urls:
            seed_base = abs(hash(query)) % 1000
            urls = [f"https://picsum.photos/seed/{seed_base + i}/800/600" for i in range(limit)]

        if urls:
            import random
            random.shuffle(urls)

        return urls[:limit]

    async def download_image_url(self, url: str) -> Optional[Tuple[bytes, str]]:
        """Downloads a specific URL and returns its bytes and content-type."""
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=15.0, headers=HEADERS) as client:
                resp = await client.get(url)
                if resp.status_code == 200 and len(resp.content) > 1000:
                    content_type = resp.headers.get("content-type", "image/jpeg").split(";")[0]
                    return resp.content, content_type
        except Exception as e:
            logger.error(f"Failed to download image URL {url}: {e}")
        return None

    async def _search_wikipedia(self, query: str) -> list[str]:
        """
        Search Wikipedia for images related to the query.
        Returns a list of image URLs.
        """
        encoded = urllib.parse.quote(query)
        url = f"https://en.wikipedia.org/w/api.php?action=query&generator=search&gsrsearch={encoded}&prop=pageimages&format=json&pithumbsize=800"
        urls = []
        try:
            async with httpx.AsyncClient(timeout=10.0, headers=HEADERS) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    pages = data.get("query", {}).get("pages", {})
                    for p in pages.values():
                        src = p.get("thumbnail", {}).get("source")
                        # Filter out common wikipedia UI icons
                        if src and not any(x in src for x in ["Commons-logo", "Ambox", "Wiktionary-logo", "Symbol_", "Flag_"]):
                            urls.append(src)
        except Exception as e:
            logger.debug(f"[Wikipedia] Failed for '{query}': {e}")
        return urls

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
