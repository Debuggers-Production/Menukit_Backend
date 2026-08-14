"""Background service to reconcile unsettled Razorpay Route transfers."""

import asyncio
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
import razorpay

from app.core.config import get_settings
from app.models.order import Order


async def reconcile_unsettled_transfers(db: AsyncSession):
    """
    Finds paid orders without a settled status and reconciles their Razorpay transfers.
    Falls back to fetching transfer_id if it's missing from the database.
    """
    settings = get_settings()

    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        print("Skipping reconciliation: Razorpay credentials not configured.")
        return

    # Find paid orders that are not settled, have a payment session ID (Razorpay payment ID),
    # and are not mock orders
    stmt = select(Order).where(
        Order.payment_status == "paid",
        (Order.settlement_status == None) | (Order.settlement_status != "settled"),
        Order.payment_session_id != None,
        Order.razorpay_order_id != None,
        ~Order.razorpay_order_id.startswith("order_mock_")
    )
    
    result = await db.execute(stmt)
    unsettled_orders = result.scalars().all()
    
    if not unsettled_orders:
        return

    print(f"DEBUG: Found {len(unsettled_orders)} unsettled orders. Reconciling...")
    
    # Initialize Razorpay client
    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

    for order in unsettled_orders:
        try:
            transfer_id = order.razorpay_transfer_id

            # Fallback: Fetch transfer_id dynamically if missing
            if not transfer_id:
                print(f"DEBUG: Transfer ID missing for order {order.id}. Fetching from Razorpay...")
                # Fetch transfers associated with the payment_id (which is saved in payment_session_id)
                transfers = client.transfer.all({'payment_id': order.payment_session_id})
                
                if transfers and 'items' in transfers and len(transfers['items']) > 0:
                    transfer_id = transfers['items'][0]['id']
                    # Save the transfer_id for future use
                    order.razorpay_transfer_id = transfer_id
                    await db.commit()
                    print(f"DEBUG: Saved transfer ID {transfer_id} for order {order.id}.")
                else:
                    print(f"DEBUG: No transfers found for payment {order.payment_session_id} (order {order.id}).")
                    continue

            # Fetch specific transfer details as requested: GET /v1/transfers/{transfer_id}
            transfer_details = client.transfer.fetch(transfer_id)
            
            # Check settlement status
            status = transfer_details.get("settlement_status")
            if not status:
                # If settlement_status is not present, fallback to main status
                status = transfer_details.get("status")

            if status == "settled" or status == "processed":
                order.settlement_status = "settled"
                order.settled_at = datetime.now(timezone.utc)
                # Ensure we also store the razorpay_settlement_id if available on the transfer
                order.razorpay_settlement_id = transfer_details.get("recipient_settlement_id") or transfer_details.get("settlement_id")
                await db.commit()
                print(f"DEBUG: Reconciled order {order.id}. Settlement status updated to settled.")
            else:
                print(f"DEBUG: Order {order.id} (transfer {transfer_id}) is still {status}.")

        except Exception as e:
            print(f"Error reconciling order {order.id}: {e}")
            await db.rollback()
