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
                unix_time = transfer_details.get("processed_at") or transfer_details.get("created_at")
                settlement_id = transfer_details.get("recipient_settlement_id") or transfer_details.get("settlement_id")
                recipient_account = transfer_details.get("recipient")
                
                if settlement_id and recipient_account:
                    import requests
                    from requests.auth import HTTPBasicAuth
                    settings = get_settings()
                    url = f"https://api.razorpay.com/v1/settlements/{settlement_id}"
                    resp = requests.get(
                        url, 
                        headers={"X-Razorpay-Account": recipient_account},
                        auth=HTTPBasicAuth(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
                    )
                    if resp.status_code == 200:
                        unix_time = resp.json().get("created_at") or unix_time

                order.settlement_status = "settled"
                order.settled_at = datetime.fromtimestamp(unix_time, timezone.utc) if unix_time else datetime.now(timezone.utc)
                # Ensure we also store the razorpay_settlement_id if available on the transfer
                order.razorpay_settlement_id = settlement_id
                await db.commit()
                print(f"DEBUG: Reconciled order {order.id}. Settlement status updated to settled.")
            else:
                print(f"DEBUG: Order {order.id} (transfer {transfer_id}) is still {status}.")

        except Exception as e:
            print(f"Error reconciling order {order.id}: {e}")
            await db.rollback()

async def reconcile_missed_payments(db: AsyncSession):
    """
    Finds orders that were CANCELLED (e.g., due to timeout) but the customer might have successfully paid 
    on Razorpay (and closed the browser before verification). If Razorpay holds their money, we refund it automatically.
    """
    settings = get_settings()
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        return

    # Find orders that were cancelled due to timeout, but still have 'pending' payment status locally,
    # and have a razorpay_order_id so we can check Razorpay.
    stmt = select(Order).where(
        Order.order_status == "CANCELLED",
        Order.cancellation_reason == "PAYMENT_TIMEOUT",
        Order.payment_status == "pending",
        Order.razorpay_order_id != None,
        ~Order.razorpay_order_id.startswith("order_mock_")
    )
    result = await db.execute(stmt)
    stuck_orders = result.scalars().all()
    
    if not stuck_orders:
        return
        
    print(f"DEBUG: Found {len(stuck_orders)} timed-out orders. Checking Razorpay for missed payments...")
    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

    for order in stuck_orders:
        try:
            # Fetch the order from Razorpay
            rzp_order = client.order.fetch(order.razorpay_order_id)
            if rzp_order.get("status") == "paid":
                print(f"DEBUG: Order {order.id} was CANCELLED but Razorpay says PAID! Issuing auto-refund...")
                
                # We need the payment ID to issue a refund. Fetch payments for this order.
                payments = client.order.payments(order.razorpay_order_id)
                if payments and "items" in payments and len(payments["items"]) > 0:
                    # Get the first successful payment
                    successful_payments = [p for p in payments["items"] if p.get("status") == "captured"]
                    if successful_payments:
                        payment_id = successful_payments[0]["id"]
                        
                        # Issue refund
                        refund = client.payment.refund(payment_id, {
                            "amount": int(order.total_amount * 100)
                        })
                        
                        refund_id = refund.get("id")
                        print(f"DEBUG: Successfully initiated refund {refund_id} on payment {payment_id} for order {order.id}")
                        print(f"[SMS NOTIFICATION TO CUSTOMER {order.customer_phone}]: Your refund of ₹{order.total_amount} has been initiated from Menukit.")
                        
                        # Mark as refund_initiated locally
                        order.payment_status = "refund_initiated"
                        order.payment_session_id = payment_id
                        order.refund_id = refund_id
                        await db.commit()
            else:
                # If it's not paid, we don't need to check it again. We can mark payment_status as failed/cancelled.
                order.payment_status = "cancelled"
                await db.commit()
                
        except Exception as e:
            print(f"Error checking missed payment for order {order.id}: {e}")
            await db.rollback()

async def reconcile_pending_refunds(db: AsyncSession):
    """
    Finds orders that are stuck in 'refund_initiated' and checks their refund status on Razorpay.
    """
    settings = get_settings()
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        return

    # Find orders that have a refund initiated but not completed
    stmt = select(Order).where(
        Order.payment_status == "refund_initiated",
        Order.refund_id != None
    )
    result = await db.execute(stmt)
    pending_refunds = result.scalars().all()
    
    if not pending_refunds:
        return
        
    print(f"DEBUG: Found {len(pending_refunds)} pending refunds. Checking Razorpay...")
    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

    for order in pending_refunds:
        try:
            refund = client.refund.fetch(order.refund_id)
            status = refund.get("status")
            
            if status == "processed":
                print(f"DEBUG: Refund {order.refund_id} is processed!")
                print(f"[SMS NOTIFICATION TO CUSTOMER {order.customer_phone}]: Your amount of ₹{order.total_amount} was refunded successfully by Menukit.")
                order.payment_status = "refunded"
                await db.commit()
            elif status == "failed":
                print(f"DEBUG: Refund {order.refund_id} failed!")
                order.payment_status = "refund_failed"
                await db.commit()
            else:
                print(f"DEBUG: Refund {order.refund_id} is still {status}.")
                
        except Exception as e:
            print(f"Error checking pending refund for order {order.id}: {e}")
            await db.rollback()
