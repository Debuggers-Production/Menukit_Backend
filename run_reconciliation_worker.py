"""
Compatibility wrapper for Menukit Background Worker.
Delegates to the unified background worker in run_worker.py.

Usage:
    python run_reconciliation_worker.py
    python run_reconciliation_worker.py --once
    python run_reconciliation_worker.py --interval 3600
"""

import sys
import os
import asyncio

# Ensure backend root is on sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from run_worker import main

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
