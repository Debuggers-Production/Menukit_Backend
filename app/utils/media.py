"""Media and Image URL resolution and path normalization utilities.

Guarantees:
1. In DB: Only relative object paths (e.g. 'items/abc.jpg', 'logos/xyz.jpg') are stored.
2. In API Responses: Dynamically prepends IMAGE_BASE_URL from .env so host/CDN is easily swappable anytime.
"""

from typing import Optional
from app.core.config import get_settings


def get_image_base_url() -> str:
    """Get the active base URL for images from settings / .env."""
    settings = get_settings()
    configured_base = getattr(settings, "IMAGE_BASE_URL", "").strip()
    if configured_base:
        return configured_base.rstrip("/")

    # Fallback to MinIO endpoint if configured
    if getattr(settings, "MINIO_ENDPOINT", "").strip():
        protocol = "https" if getattr(settings, "MINIO_SECURE", True) else "http"
        bucket = getattr(settings, "MINIO_BUCKET_NAME", "menukitassets") or "menukitassets"
        return f"{protocol}://{settings.MINIO_ENDPOINT.strip()}/{bucket}"

    # Fallback to local server uploads
    return "http://localhost:8000/uploads"


def strip_image_base_url(url_or_path: Optional[str]) -> Optional[str]:
    """Strip domain and protocol from URL so ONLY relative path is stored in database.

    Examples:
    - 'https://assets.menukit.../menukitassets/items/123.jpg' -> 'items/123.jpg'
    - 'http://localhost:8000/uploads/items/123.jpg' -> 'items/123.jpg'
    - '/uploads/items/123.jpg' -> 'items/123.jpg'
    - 'items/123.jpg' -> 'items/123.jpg'
    - 'https://images.pixabay.com/...' -> 'https://images.pixabay.com/...' (third-party left intact)
    """
    if not url_or_path or not isinstance(url_or_path, str):
        return url_or_path

    val = url_or_path.strip()
    if not val:
        return val

    settings = get_settings()
    configured_base = getattr(settings, "IMAGE_BASE_URL", "").strip().rstrip("/")
    bucket = getattr(settings, "MINIO_BUCKET_NAME", "") or "menukitassets"
    minio_endpoint = getattr(settings, "MINIO_ENDPOINT", "").strip().replace("https://", "").replace("http://", "")

    # Preserve external third-party images (e.g. Pixabay, Unsplash, Google profile photos)
    is_internal = False
    if configured_base and configured_base in val:
        is_internal = True
    elif bucket and bucket in val:
        is_internal = True
    elif minio_endpoint and minio_endpoint in val:
        is_internal = True
    elif "localhost" in val.lower() or "127.0.0.1" in val.lower() or "menukit" in val.lower() or "smartmenu" in val.lower():
        is_internal = True
    elif val.startswith("/"):
        is_internal = True
    elif not val.startswith("http://") and not val.startswith("https://"):
        # Relative path (e.g. 'items/abc.jpg')
        return val.lstrip("/")

    if not is_internal and (val.startswith("http://") or val.startswith("https://")):
        return val

    # 1. Strip configured_base if present
    if configured_base and configured_base in val:
        val = val.split(configured_base)[-1]

    # 2. Strip MinIO bucket path if present
    if bucket and f"/{bucket}/" in val:
        val = val.split(f"/{bucket}/")[-1]

    # 3. Strip /uploads/ if present
    if "/uploads/" in val:
        val = val.split("/uploads/")[-1]

    # 4. Strip any residual http(s)://domain/ prefix
    if val.startswith("http://") or val.startswith("https://"):
        parts = val.split("/", 3)
        if len(parts) >= 4:
            val = parts[3]

    return val.lstrip("/")


def resolve_image_url(path_or_url: Optional[str]) -> Optional[str]:
    """Dynamically resolve an image path or URL using IMAGE_BASE_URL from .env.

    Examples:
    - 'items/123.jpg' -> 'https://assets.../menukitassets/items/123.jpg'
    - 'http://localhost:8000/uploads/items/123.jpg' -> 'https://assets.../menukitassets/items/123.jpg'
    - 'https://images.pixabay.com/...' -> 'https://images.pixabay.com/...'
    """
    if not path_or_url or not isinstance(path_or_url, str):
        return path_or_url

    val = path_or_url.strip()
    if not val:
        return val

    settings = get_settings()
    configured_base = getattr(settings, "IMAGE_BASE_URL", "").strip().rstrip("/")
    bucket = getattr(settings, "MINIO_BUCKET_NAME", "") or "menukitassets"
    minio_endpoint = getattr(settings, "MINIO_ENDPOINT", "").strip().replace("https://", "").replace("http://", "")

    # Check if external third-party image (keep as-is)
    is_internal = False
    if configured_base and configured_base in val:
        is_internal = True
    elif bucket and bucket in val:
        is_internal = True
    elif minio_endpoint and minio_endpoint in val:
        is_internal = True
    elif "localhost" in val.lower() or "127.0.0.1" in val.lower() or "menukit" in val.lower() or "smartmenu" in val.lower():
        is_internal = True
    elif not val.startswith("http://") and not val.startswith("https://"):
        is_internal = True

    if not is_internal and (val.startswith("http://") or val.startswith("https://")):
        return val

    # Clean the path to get the pure relative object key (e.g. 'items/abc.jpg')
    clean_path = strip_image_base_url(val)
    if not clean_path:
        return val

    base_url = get_image_base_url()
    return f"{base_url}/{clean_path}"

