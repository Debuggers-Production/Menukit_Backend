"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.api.v1.router import api_router
from app.database.session import init_db, close_db, init_chalkboard_table
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
    logger.info("Starting up SmartMenu QR backend with migration...")
    try:
        import asyncio
        # await asyncio.wait_for(init_chalkboard_table(), timeout=5.0)
    except Exception as e:
        logger.warning(f"Chalkboard table init failed or timed out: {e}")
    try:
        await init_redis()
        logger.info("Redis connected.")
    except Exception as e:
        logger.warning(f"Redis unavailable — running without cache: {e}")
        
    from app.services.reconciliation_service import reconcile_unsettled_transfers, reconcile_missed_payments, reconcile_pending_refunds
    from app.database.session import async_session_factory
    import asyncio
    
    async def run_reconciliation_job():
        # Wait 5 minutes before the first run so app has time to start completely
        await asyncio.sleep(300)
        while True:
            try:
                async with async_session_factory() as db:
                    await reconcile_missed_payments(db)
                    await reconcile_unsettled_transfers(db)
                    await reconcile_pending_refunds(db)
            except Exception as e:
                logger.error(f"Error in reconciliation job: {e}")
            finally:
                # Sleep for 3 hours (3 * 3600 seconds = 10800)
                await asyncio.sleep(10800)
                
    from app.services.timeout_service import process_payment_timeouts
    
    async def run_timeout_job():
        await asyncio.sleep(5)
        await process_payment_timeouts()

    from app.services.scheduled_notification_service import ScheduledNotificationService

    async def run_scheduled_notifications_job():
        # Wait 20 seconds after app startup
        await asyncio.sleep(20)
        while True:
            try:
                async with async_session_factory() as db:
                    # 1. Check subscriptions (3 days before and every 2 days after expired)
                    sub_res = await ScheduledNotificationService.process_subscription_expiry_checks(db)
                    logger.info(f"Scheduled subscription check completed: {sub_res}")

                    # 2. Check weekend customer report (every weekend in IST)
                    weekend_res = await ScheduledNotificationService.process_weekend_customer_reports(db)
                    logger.info(f"Weekend customer reports check completed: {weekend_res}")

                    # 3. Check scheme fund payment reminders (1 day before due date)
                    scheme_res = await ScheduledNotificationService.process_scheme_payment_reminders(db)
                    logger.info(f"Scheme payment reminders check completed: {scheme_res}")
            except Exception as e:
                logger.error(f"Error in scheduled notifications job: {e}")
            finally:
                # Run periodically every 1 hour (3600 seconds)
                await asyncio.sleep(3600)
        
    timeout_task = asyncio.create_task(run_timeout_job())
    job_task = asyncio.create_task(run_reconciliation_job())
    sched_notif_task = asyncio.create_task(run_scheduled_notifications_job())
    
    yield
    
    timeout_task.cancel()
    job_task.cancel()
    sched_notif_task.cancel()
    
    # Shutdown
    logger.info("Shutting down...")
    await close_db()
    await close_redis()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    is_prod = getattr(settings, "is_production", False)

    app = FastAPI(
        title=settings.APP_NAME,
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None if is_prod else "/docs",
        redoc_url=None if is_prod else "/redoc",
        openapi_url=None if is_prod else "/openapi.json",
    )

    # Configure CORS

    
    
    # ALLOWED_ORIGINS=[settings.FRONTEND_URL, "http://localhost:5173/", "http://127.0.0.1:8002","http://localhost:5174/","http://localhost:5174/landing/","https://menukit.debuggerstechnologies.com/","https://menukit.debuggerstechnologies.com/landing/"]
    ALLOWED_ORIGINS=["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        max_age=86400,
    )

    from fastapi.middleware.gzip import GZipMiddleware
    app.add_middleware(GZipMiddleware, minimum_size=500)

    # Include API router
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    from fastapi.responses import PlainTextResponse

    @app.get("/.well-known/openai-apps-challenge", response_class=PlainTextResponse)
    async def openai_apps_challenge_verification():
        import os
        return os.getenv("OPENAI_VERIFICATION_TOKEN","")

    import time
    from fastapi import HTTPException, Request
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse
    from fastapi.exception_handlers import (
        http_exception_handler as default_http_exception_handler,
        request_validation_exception_handler as default_validation_exception_handler,
    )

    @app.exception_handler(HTTPException)
    async def custom_http_exception_handler(request: Request, exc: HTTPException):
        request.state.error_detail = str(exc.detail)
        logger.error(f"\033[91m❌ HTTP {exc.status_code} Error on {request.method} {request.url.path}:\033[0m {exc.detail}")
        return await default_http_exception_handler(request, exc)

    @app.exception_handler(RequestValidationError)
    async def custom_validation_exception_handler(request: Request, exc: RequestValidationError):
        request.state.error_detail = str(exc.errors())
        logger.error(f"\033[91m❌ Validation Error on {request.method} {request.url.path}:\033[0m {exc.errors()}")
        return await default_validation_exception_handler(request, exc)

    @app.middleware("http")
    async def rate_limit_requests(request: Request, call_next):
        # Bypass rate limiting in development mode
        if str(getattr(settings, "APP_ENV", "")).lower() in ["development", "dev", "local"] or getattr(settings, "DEBUG", False):
            return await call_next(request)

        # Only rate limit API routes
        if not request.url.path.startswith("/api/"):
            return await call_next(request)
            
        # Define limits per minute based on HTTP method
        if request.method in ["POST", "PUT", "DELETE"]:
            limit = 60
        else:
            limit = 200
            
        # Identify user by their token or IP
        client_ip = request.client.host if request.client else "127.0.0.1"
        auth = request.headers.get("Authorization", "")
        identifier = auth[-15:] if auth and auth.startswith("Bearer ") else client_ip
        
        current_minute = int(time.time() / 60)
        redis_key = f"rate_limit:{request.method}:{identifier}:{current_minute}"
        
        try:
            from app.database.redis import get_redis
            r_client = await get_redis()
            # If r_client is real redis, execute with timeout guard
            import asyncio
            reqs = await asyncio.wait_for(r_client.incr(redis_key), timeout=0.1)
            if reqs == 1:
                await asyncio.wait_for(r_client.expire(redis_key, 60), timeout=0.1)
                
            if reqs > limit:
                from fastapi.responses import JSONResponse
                return JSONResponse(
                    status_code=429, 
                    content={"detail": f"Rate limit exceeded. Maximum {limit} requests per minute."}
                )
        except Exception as e:
            # Fail open instantly if Redis is down or timing out
            pass
            
        return await call_next(request)

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start_time = time.time()
        
        # ANSI Escape Codes
        RESET = "\033[0m"
        BLUE = "\033[94m"
        GREEN = "\033[92m"
        YELLOW = "\033[93m"
        RED = "\033[91m"
        CYAN = "\033[96m"
        MAGENTA = "\033[95m"

        # Method Color Logic
        if request.method == "GET":
            method_color = CYAN
        elif request.method == "POST":
            method_color = GREEN
        elif request.method == "PUT":
            method_color = YELLOW
        elif request.method == "DELETE":
            method_color = RED
        else:
            method_color = MAGENTA
        
        # Log request start
        logger.info(f"{BLUE}▶ Incoming:{RESET} {method_color}{request.method}{RESET} {request.url.path}")
        
        # Process request
        response = await call_next(request)
        
        process_time = (time.time() - start_time) * 1000
        formatted_process_time = f"{process_time:.2f}ms"
        
        # Color based on status code
        if response.status_code < 300:
            status_color = GREEN
        elif response.status_code < 400:
            status_color = YELLOW
        else:
            status_color = RED
            
        error_msg = ""
        if response.status_code >= 400 and hasattr(request.state, "error_detail"):
            error_msg = f" - {RED}Error: {request.state.error_detail}{RESET}"
            
        # Log request end with status code and time
        logger.info(f"{MAGENTA}✔ Completed:{RESET} {method_color}{request.method}{RESET} {request.url.path} - {status_color}Status: {response.status_code}{RESET} - {YELLOW}Time: {formatted_process_time}{RESET}{error_msg}")
        
        return response


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

