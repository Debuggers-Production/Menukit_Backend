"""IP Geolocation and Country Detection Service."""

import logging
from typing import Optional, Dict
import httpx
from fastapi import Request
from app.services.pricing_engine import COUNTRIES_CONFIG, CountryConfig

logger = logging.getLogger(__name__)


class GeoService:
    """Service to automatically detect visitor country using IP and headers."""

    _ip_cache: Dict[str, str] = {}

    @classmethod
    def get_client_ip(cls, request: Request) -> str:
        """Extract client IP from proxy headers or socket address."""
        # 1. Cloudflare
        cf_ip = request.headers.get("cf-connecting-ip")
        if cf_ip:
            return cf_ip.split(",")[0].strip()

        # 2. X-Forwarded-For
        x_forwarded = request.headers.get("x-forwarded-for")
        if x_forwarded:
            return x_forwarded.split(",")[0].strip()

        # 3. X-Real-IP
        x_real = request.headers.get("x-real-ip")
        if x_real:
            return x_real.strip()

        # 4. Fallback client host
        if request.client and request.client.host:
            return request.client.host

        return "127.0.0.1"

    @classmethod
    async def detect_country_code(cls, request: Request) -> str:
        """
        Detect visitor country code (e.g. IN, US, GB, AU, CA, EU, OTHER).
        Checks headers first, then cached IP, then free IP geolocation.
        """
        # 1. Cloudflare Header
        cf_country = request.headers.get("cf-ipcountry")
        if cf_country and len(cf_country) == 2:
            cf_code = cf_country.upper().strip()
            if cf_code in COUNTRIES_CONFIG:
                return cf_code
            return "OTHER"

        # 2. Custom header
        header_country = request.headers.get("x-country-code")
        if header_country and header_country.upper() in COUNTRIES_CONFIG:
            return header_country.upper()

        # 3. Client IP lookup
        client_ip = cls.get_client_ip(request)

        # Check in-memory IP cache
        if client_ip in cls._ip_cache:
            return cls._ip_cache[client_ip]

        # 4. Geolocation APIs (Primary: api.country.is, Secondary: ip-api.com)
        is_local = client_ip in ("127.0.0.1", "localhost", "::1") or client_ip.startswith(("192.168.", "10.", "172.16."))

        # Try api.country.is
        try:
            url = "https://api.country.is" if is_local else f"https://api.country.is/{client_ip}"
            async with httpx.AsyncClient(timeout=2.0) as client:
                res = await client.get(url)
                if res.status_code == 200:
                    data = res.json()
                    country = (data.get("country") or "").upper().strip()
                    if len(country) == 2:
                        matched = country if country in COUNTRIES_CONFIG else "OTHER"
                        if not is_local:
                            cls._ip_cache[client_ip] = matched
                        return matched
        except Exception as e:
            logger.debug(f"api.country.is lookup failed: {e}")

        # Try ip-api.com fallback
        try:
            url = "http://ip-api.com/json" if is_local else f"http://ip-api.com/json/{client_ip}"
            async with httpx.AsyncClient(timeout=2.0) as client:
                res = await client.get(url)
                if res.status_code == 200:
                    data = res.json()
                    country = (data.get("countryCode") or "").upper().strip()
                    if len(country) == 2:
                        matched = country if country in COUNTRIES_CONFIG else "OTHER"
                        if not is_local:
                            cls._ip_cache[client_ip] = matched
                        return matched
        except Exception as e:
            logger.debug(f"ip-api.com lookup failed: {e}")

        # Default fallback
        return "IN"

    @classmethod
    async def get_detected_country_config(cls, request: Request) -> CountryConfig:
        """Get full CountryConfig for the detected visitor."""
        code = await cls.detect_country_code(request)
        return COUNTRIES_CONFIG.get(code, COUNTRIES_CONFIG["OTHER"])


geo_service = GeoService()

