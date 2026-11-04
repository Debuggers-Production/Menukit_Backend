"""
Standalone Background Worker for Menukit.
Combines and runs all heavy periodic background jobs in a dedicated out-of-process instance:
1. Scheduled Notifications (Subscription expiry alerts, Weekend customer digests, Scheme payment reminders)
2. Payment Reconciliation (Missed payments on cancelled orders, Unsettled Razorpay transfers, Pending refunds)
3. Broadcast Marketing Campaigns (Scheduled WhatsApp broadcast messages dispatch)

Running this worker in a separate instance ensures the FastAPI web/WebSocket server process
remains completely responsive without event loop lag or blocking database connections.

Usage:
    # Run all combined workers continuously:
    python run_worker.py

    # Run all combined workers once and exit (for cron jobs or testing):
    python run_worker.py --once

    # Custom intervals:
    python run_worker.py --notifications-interval 3600 --reconciliation-interval 3600 --campaigns-interval 60

    # Selectively disable specific tasks:
    python run_worker.py --disable-reconciliation
    python run_worker.py --disable-notifications
    python run_worker.py --disable-campaigns
"""

import sys
import os
import time
import signal
import asyncio
import argparse
import logging
from datetime import datetime

# Ensure backend root is on sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, ".env"))

from app.core.config import get_settings
from app.database.session import async_session_factory, close_db, engine
from app.database.redis import init_redis, close_redis

# Services
from app.services.reconciliation_service import (
    reconcile_unsettled_transfers,
    reconcile_missed_payments,
    reconcile_pending_refunds,
)
from app.services.scheduled_notification_service import ScheduledNotificationService
from app.services.broadcast_service import BroadcastService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger("Worker")
recon_logger = logging.getLogger("ReconcileWorker")
notif_logger = logging.getLogger("NotifWorker")
camp_logger = logging.getLogger("CampaignWorker")

stop_requested = False


def handle_shutdown(sig, frame):
    global stop_requested
    logger.info("Shutdown signal received. Stopping worker gracefully...")
    stop_requested = True


async def safe_sleep(seconds: int):
    """Sleep in 1-second chunks so the process responds promptly to shutdown signals."""
    for _ in range(seconds):
        if stop_requested:
            break
        await asyncio.sleep(1)


# ============================================================================
# 1. Reconciliation Tasks
# ============================================================================
async def run_reconciliation_pass():
    """Execute one full pass of payment reconciliation tasks."""
    recon_logger.info("Starting reconciliation pass...")
    start_time = time.time()
    try:
        async with async_session_factory() as db:
            recon_logger.info("[1/3] Checking missed payments on cancelled orders...")
            await reconcile_missed_payments(db)

            recon_logger.info("[2/3] Checking unsettled Razorpay transfers...")
            await reconcile_unsettled_transfers(db)

            recon_logger.info("[3/3] Checking pending refunds status...")
            await reconcile_pending_refunds(db)

        elapsed = time.time() - start_time
        recon_logger.info(f"Reconciliation pass finished in {elapsed:.2f}s.")
    except Exception as e:
        recon_logger.error(f"Error during reconciliation pass: {e}", exc_info=True)


async def reconciliation_loop(interval_sec: int):
    """Periodic loop for payment reconciliation."""
    recon_logger.info(f"Reconciliation worker loop started (interval: {interval_sec}s).")
    # Initial short wait so other startup tasks initialize
    await safe_sleep(5)
    while not stop_requested:
        await run_reconciliation_pass()
        if stop_requested:
            break
        recon_logger.info(f"Reconciliation sleeping for {interval_sec}s until next run...")
        await safe_sleep(interval_sec)


# ============================================================================
# 2. Scheduled Notifications Tasks
# ============================================================================
async def run_notifications_pass():
    """Execute one full pass of scheduled notification tasks."""
    notif_logger.info("Starting scheduled notifications pass...")
    start_time = time.time()
    try:
        async with async_session_factory() as db:
            # 1. Subscription Expiry Checks
            notif_logger.info("[1/3] Checking subscriptions nearing expiry or expired...")
            sub_res = await ScheduledNotificationService.process_subscription_expiry_checks(db)
            notif_logger.info(f"Subscription check result: {sub_res}")

            # 2. Weekend Customer Reports
            notif_logger.info("[2/3] Checking weekend customer digests...")
            weekend_res = await ScheduledNotificationService.process_weekend_customer_reports(db)
            notif_logger.info(f"Weekend customer reports result: {weekend_res}")

            # 3. Scheme Fund Payment Reminders
            notif_logger.info("[3/3] Checking scheme payment reminders...")
            scheme_res = await ScheduledNotificationService.process_scheme_payment_reminders(db)
            notif_logger.info(f"Scheme reminders result: {scheme_res}")

        elapsed = time.time() - start_time
        notif_logger.info(f"Scheduled notifications pass finished in {elapsed:.2f}s.")
    except Exception as e:
        notif_logger.error(f"Error during scheduled notifications pass: {e}", exc_info=True)


async def notifications_loop(interval_sec: int):
    """Periodic loop for scheduled notifications."""
    notif_logger.info(f"Scheduled notifications worker loop started (interval: {interval_sec}s).")
    await safe_sleep(2)
    while not stop_requested:
        await run_notifications_pass()
        if stop_requested:
            break
        notif_logger.info(f"Notifications worker sleeping for {interval_sec}s until next run...")
        await safe_sleep(interval_sec)


# ============================================================================
# 3. Broadcast Campaigns Tasks
# ============================================================================
async def run_campaigns_pass():
    """Check and dispatch any scheduled broadcast campaigns that are due."""
    try:
        async with async_session_factory() as db:
            bs = BroadcastService(db)
            await bs.dispatch_due_scheduled_campaigns()
    except Exception as e:
        camp_logger.error(f"Error checking due broadcast campaigns: {e}", exc_info=True)


async def campaigns_loop(interval_sec: int):
    """Periodic loop for broadcast marketing campaigns."""
    camp_logger.info(f"Broadcast campaigns worker loop started (interval: {interval_sec}s).")
    await safe_sleep(3)
    while not stop_requested:
        await run_campaigns_pass()
        if stop_requested:
            break
        await safe_sleep(interval_sec)


# ============================================================================
# Main Entry Point
# ============================================================================
async def main():
    parser = argparse.ArgumentParser(description="Menukit Unified Background Worker")
    parser.add_argument("--once", action="store_true", help="Run one pass of all enabled tasks and exit")
    parser.add_argument("--notifications-interval", type=int, default=3600, help="Notifications poll interval in seconds (default: 3600s / 1 hr)")
    parser.add_argument("--reconciliation-interval", type=int, default=3600, help="Reconciliation poll interval in seconds (default: 3600s / 1 hr)")
    parser.add_argument("--campaigns-interval", type=int, default=60, help="Campaigns poll interval in seconds (default: 60s / 1 min)")
    parser.add_argument("--disable-reconciliation", action="store_true", help="Disable the payment reconciliation job")
    parser.add_argument("--disable-notifications", action="store_true", help="Disable the scheduled notifications job")
    parser.add_argument("--disable-campaigns", action="store_true", help="Disable the scheduled campaigns job")
    args = parser.parse_args()

    settings = get_settings()
    logger.info("=" * 70)
    logger.info("Menukit Standalone Unified Background Worker")
    logger.info(f"App: {settings.APP_NAME}")
    logger.info(f"Mode: {'ONE-OFF PASS (--once)' if args.once else 'CONTINUOUS SERVICE'}")
    logger.info(f"Reconciliation: {'DISABLED' if args.disable_reconciliation else f'ENABLED (every {args.reconciliation_interval}s)'}")
    logger.info(f"Notifications:  {'DISABLED' if args.disable_notifications else f'ENABLED (every {args.notifications_interval}s)'}")
    logger.info(f"Campaigns:      {'DISABLED' if args.disable_campaigns else f'ENABLED (every {args.campaigns_interval}s)'}")
    logger.info("=" * 70)

    # Register OS signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    # Initialize Redis if configured
    try:
        await init_redis()
        logger.info("Redis cache initialized.")
    except Exception as e:
        logger.warning(f"Redis unavailable for worker (continuing without cache): {e}")

    try:
        if args.once:
            # Execute all tasks sequentially once
            if not args.disable_campaigns:
                logger.info("--- [1/3] Running Campaigns Pass ---")
                await run_campaigns_pass()
            if not args.disable_notifications:
                logger.info("--- [2/3] Running Scheduled Notifications Pass ---")
                await run_notifications_pass()
            if not args.disable_reconciliation:
                logger.info("--- [3/3] Running Payment Reconciliation Pass ---")
                await run_reconciliation_pass()
            logger.info("Single pass execution completed successfully.")
            return

        # Run worker loops concurrently
        tasks = []
        if not args.disable_campaigns:
            tasks.append(asyncio.create_task(campaigns_loop(args.campaigns_interval)))
        if not args.disable_notifications:
            tasks.append(asyncio.create_task(notifications_loop(args.notifications_interval)))
        if not args.disable_reconciliation:
            tasks.append(asyncio.create_task(reconciliation_loop(args.reconciliation_interval)))

        if not tasks:
            logger.warning("No worker jobs were enabled. Exiting.")
            return

        await asyncio.gather(*tasks, return_exceptions=True)

    finally:
        logger.info("Cleaning up connections and shutting down...")
        try:
            await close_db()
        except Exception:
            pass
        try:
            await close_redis()
        except Exception:
            pass
        logger.info("Unified background worker terminated cleanly.")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())

