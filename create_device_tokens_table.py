import asyncio
import logging
from sqlalchemy import text
from app.database.session import engine
from app.database.base import Base
from app.models.device_token import DeviceToken

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def init_device_tokens_table():
    async with engine.begin() as conn:
        logger.info("Ensuring device_tokens table exists...")
        await conn.run_sync(Base.metadata.create_all, tables=[DeviceToken.__table__])
        logger.info("device_tokens table checked/created successfully.")

if __name__ == "__main__":
    asyncio.run(init_device_tokens_table())
