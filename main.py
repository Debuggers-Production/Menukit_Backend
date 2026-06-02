"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.api.v1.router import api_router
from app.database.session import init_db, close_db
from app.database.redis import init_redis, close_redis, get_redis

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle events for the FastAPI application."""
    # Startup
    logger.info("Starting up SmartMenu QR backend...")
    await init_db()
    try:
        await init_redis()
        redis_client = await get_redis()
        await redis_client.flushdb()  # Clear Redis on startup for a clean slate
        logger.info("Redis connected and flushed.")
    except Exception as e:
        logger.warning(f"Redis unavailable — running without cache: {e}")
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    await close_db()
    await close_redis()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=settings.APP_NAME,
        version="1.0.0",
        lifespan=lifespan,
    )

    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.FRONTEND_URL, "http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include API router
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    # Serve uploaded files if using local storage
    if not settings.AZURE_STORAGE_CONNECTION_STRING:
        import os
        from pathlib import Path
        
        upload_dir = Path(settings.UPLOAD_DIR)
        upload_dir.mkdir(parents=True, exist_ok=True)
        
        app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")

    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {"status": "ok", "app": settings.APP_NAME}

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=settings.DEBUG)


import secrets


print("SECRET_KEY:", secrets.token_urlsafe(32))
