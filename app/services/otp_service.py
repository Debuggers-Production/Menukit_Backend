"""OTP service for generating and verifying one-time passwords."""

import random
import string
from datetime import datetime, timedelta, timezone
from typing import Optional

import redis.asyncio as redis
from app.core.config import get_settings

settings = get_settings()


class OTPService:
    """Manages OTP generation, storage, and verification via Redis."""

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.prefix = "otp:"
        self.rate_prefix = "otp_rate:"

    def _generate_code(self) -> str:
        """Generate a 6-digit OTP code."""
        return "".join(random.choices(string.digits, k=6))

    async def _check_rate_limit(self, email: str) -> bool:
        """Check if the email has exceeded the OTP rate limit."""
        key = f"{self.rate_prefix}{email}"
        count = await self.redis.get(key)
        if count and int(count) >= settings.OTP_MAX_ATTEMPTS:
            return False
        return True

    async def _increment_rate_limit(self, email: str):
        """Increment the rate limit counter for an email."""
        key = f"{self.rate_prefix}{email}"
        pipe = self.redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, settings.OTP_RATE_LIMIT_SECONDS)
        await pipe.execute()

    async def create_otp(self, email: str) -> Optional[str]:
        """Create and store a new OTP for the given email.

        Returns the OTP code, or None if rate limited.
        """
        if not await self._check_rate_limit(email):
            return None

        code = self._generate_code()
        key = f"{self.prefix}{email}"

        # Store OTP in Redis with expiration
        await self.redis.setex(key, settings.OTP_EXPIRE_SECONDS, code)
        await self._increment_rate_limit(email)

        return code

    async def verify_otp(self, email: str, code: str) -> bool:
        """Verify an OTP code for the given email."""
        key = f"{self.prefix}{email}"
        stored_code = await self.redis.get(key)

        if stored_code and stored_code == code:
            # Delete the OTP after successful verification
            await self.redis.delete(key)
            return True

        return False
