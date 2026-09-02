"""Real-Time Foreign Exchange (FX) Rate Service with Multi-Layer Caching and Fallbacks."""

import time
import logging
from typing import Dict, Optional
import httpx

logger = logging.getLogger(__name__)

# Fallback baseline rates if all remote APIs are unreachable (1 INR in target currency)
DEFAULT_INR_RATES: Dict[str, float] = {
    "INR": 1.0,
    "USD": 0.0116,   # ~86.20 INR/USD
    "GBP": 0.0091,   # ~109.89 INR/GBP
    "AUD": 0.0178,   # ~56.18 INR/AUD
    "CAD": 0.0157,   # ~63.69 INR/CAD
    "EUR": 0.0108,   # ~92.59 INR/EUR
    "SGD": 0.0155,   # ~64.50 INR/SGD
    "AED": 0.0426,   # ~23.47 INR/AED
}

CACHE_TTL_SECONDS = 6 * 3600  # 6 Hours


class FXService:
    """Service to fetch, cache, and provide real-time currency exchange rates."""

    _cached_rates: Dict[str, float] = dict(DEFAULT_INR_RATES)
    _last_fetched: float = 0.0

    @classmethod
    async def get_rates(cls, force_refresh: bool = False) -> Dict[str, float]:
        """Get latest exchange rates for 1 INR to various currencies with caching."""
        now = time.time()
        if not force_refresh and (now - cls._last_fetched < CACHE_TTL_SECONDS) and cls._last_fetched > 0:
            return cls._cached_rates

        fetched_rates = await cls._fetch_live_rates()
        if fetched_rates:
            cls._cached_rates.update(fetched_rates)
            cls._last_fetched = now
            logger.info("FX rates successfully refreshed and cached.")
        elif cls._last_fetched == 0:
            # Initial state with defaults
            cls._last_fetched = now
            logger.warning("Using fallback default FX rates.")

        return cls._cached_rates

    @classmethod
    async def _fetch_live_rates(cls) -> Optional[Dict[str, float]]:
        """Attempt to fetch rates from primary and secondary FX providers."""
        # 1. Primary: open.er-api.com
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                res = await client.get("https://open.er-api.com/v6/latest/INR")
                if res.status_code == 200:
                    data = res.json()
                    rates = data.get("rates", {})
                    if "USD" in rates:
                        return {curr: float(rate) for curr, rate in rates.items()}
        except Exception as e:
            logger.warning(f"Primary FX provider (open.er-api.com) failed: {e}")

        # 2. Secondary: Frankfurter
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                res = await client.get("https://api.frankfurter.app/latest?from=INR")
                if res.status_code == 200:
                    data = res.json()
                    rates = data.get("rates", {})
                    if "USD" in rates:
                        rates_dict = {curr: float(rate) for curr, rate in rates.items()}
                        rates_dict["INR"] = 1.0
                        return rates_dict
        except Exception as e:
            logger.warning(f"Secondary FX provider (frankfurter.app) failed: {e}")

        # 3. Tertiary: exchangerate-api.com v4
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                res = await client.get("https://api.exchangerate-api.com/v4/latest/INR")
                if res.status_code == 200:
                    data = res.json()
                    rates = data.get("rates", {})
                    if "USD" in rates:
                        return {curr: float(rate) for curr, rate in rates.items()}
        except Exception as e:
            logger.warning(f"Tertiary FX provider failed: {e}")

        return None

    @classmethod
    async def get_rate_for_currency(cls, currency: str) -> float:
        """Get exchange rate: 1 INR = X target currency."""
        currency = currency.upper().strip()
        if currency == "INR":
            return 1.0
        rates = await cls.get_rates()
        return rates.get(currency, DEFAULT_INR_RATES.get(currency, 0.0116))

    @classmethod
    async def convert_inr_to_local(cls, amount_inr: float, currency: str) -> float:
        """Convert an INR amount to target currency before rounding."""
        rate = await cls.get_rate_for_currency(currency)
        return amount_inr * rate


# Global instance
fx_service = FXService()
