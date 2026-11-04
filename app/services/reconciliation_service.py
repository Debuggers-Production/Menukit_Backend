"""Background service to reconcile unsettled Razorpay Route transfers and missed payments asynchronously without blocking the event loop."""

import asyncio
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
import razorpay

from app.core.config import get_settings
from app.models.order import Order


def _get_razorpay_client(key_id: str, key_secret: str, timeout: int = 5):
    """Instantiate a Razorpay client configured with strict connection and read timeouts."""
    client = razorpay.Client(auth=(key_id, key_secret))
    orig_request = client.session.request

    def request_with_timeout(*args, **kwargs):
        if "timeout" not in kwargs or kwargs["timeout"] is None:
            kwargs["timeout"] = timeout
        return orig_request(*args, **kwargs)

    client.session.request = request_with_timeout
    return client


async def reconcile_unsettled_transfers(db: AsyncSession):
    """
    Finds paid orders without a settled status and reconciles their Razorpay transfers.
    Falls back to fetching transfer_id if it's missing from the database.
    Runs non-blocking on thread pool to keep the FastAPI event loop responsive.
    """
    settings = get_settings()

    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
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
    
    client = _get_razorpay_client(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET, timeout=5)

    for order in unsettled_orders:
        try:
            transfer_id = order.razorpay_transfer_id

            # Fallback: Fetch transfer_id dynamically if missing
            if not transfer_id:
                print(f"DEBUG: Transfer ID missing for order {order.id}. Fetching from Razorpay...")
                transfers = await asyncio.to_thread(
                    client.transfer.all, {'payment_id': order.payment_session_id}
                )
                
                if transfers and 'items' in transfers and len(transfers['items']) > 0:
                    transfer_id = transfers['items'][0]['id']
                    order.razorpay_transfer_id = transfer_id
                    await db.commit()
                    print(f"DEBUG: Saved transfer ID {transfer_id} for order {order.id}.")
                else:
                    print(f"DEBUG: No transfers found for payment {order.payment_session_id} (order {order.id}).")
                    continue

            # Fetch specific transfer details asynchronously via thread pool
            transfer_details = await asyncio.to_thread(client.transfer.fetch, transfer_id)
            
            # Check settlement status
            status = transfer_details.get("settlement_status") or transfer_details.get("status")

            if status in ("settled", "processed"):
                unix_time = transfer_details.get("processed_at") or transfer_details.get("created_at")
                settlement_id = transfer_details.get("recipient_settlement_id") or transfer_details.get("settlement_id")
                recipient_account = transfer_details.get("recipient")
                
                if settlement_id and recipient_account:
                    import requests
                    from requests.auth import HTTPBasicAuth
                    url = f"https://api.razorpay.com/v1/settlements/{settlement_id}"

                    def _fetch_settlement():
                        return requests.get(
                            url, 
                            headers={"X-Razorpay-Account": recipient_account},
                            auth=HTTPBasicAuth(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET),
                            timeout=5.0
                        )

                    try:
                        resp = await asyncio.to_thread(_fetch_settlement)
                        if resp.status_code == 200:
                            unix_time = resp.json().get("created_at") or unix_time
                    except Exception as s_err:
                        print(f"DEBUG: Settlement details fetch warning for {settlement_id}: {s_err}")

                order.settlement_status = "settled"
                order.settled_at = datetime.fromtimestamp(unix_time, timezone.utc) if unix_time else datetime.now(timezone.utc)
                order.razorpay_settlement_id = settlement_id
                await db.commit()
                print(f"DEBUG: Reconciled order {order.id}. Settlement status updated to settled.")
            else:
                print(f"DEBUG: Order {order.id} (transfer {transfer_id}) is still {status}.")
        except Exception as e:
            print(f"Error reconciling order {order.id}: {e}")
            await db.rollback()
        finally:
            # Yield to event loop between orders
            await asyncio.sleep(0.05)


async def reconcile_missed_payments(db: AsyncSession):
    """
    Finds orders that were CANCELLED (e.g., due to timeout) but the customer might have successfully paid 
    on Razorpay (and closed the browser before verification). If Razorpay holds their money, we refund it automatically.
    """
    settings = get_settings()
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        return

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
    client = _get_razorpay_client(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET, timeout=5)

    for order in stuck_orders:
        try:
            rzp_order = await asyncio.to_thread(client.order.fetch, order.razorpay_order_id)
            if rzp_order.get("status") == "paid":
                print(f"DEBUG: Order {order.id} was CANCELLED but Razorpay says PAID! Issuing auto-refund...")
                payments = await asyncio.to_thread(client.order.payments, order.razorpay_order_id)
                if payments and "items" in payments and len(payments["items"]) > 0:
                    successful_payments = [p for p in payments["items"] if p.get("status") == "captured"]
                    if successful_payments:
                        payment_id = successful_payments[0]["id"]
                        
                        refund = await asyncio.to_thread(
                            client.payment.refund,
                            payment_id,
                            {
                                "amount": int(order.total_amount * 100),
                                "reverse_all": 1
                            }
                        )
                        refund_id = refund.get("id")
                        print(f"DEBUG: Successfully initiated refund {refund_id} on payment {payment_id} for order {order.id}")
                        print(f"[SMS NOTIFICATION TO CUSTOMER {order.customer_phone}]: Your refund of ₹{order.total_amount} has been initiated from Menukit.")
                        
                        order.payment_status = "refund_initiated"
                        order.payment_session_id = payment_id
                        order.refund_id = refund_id
                        await db.commit()
            else:
                order.payment_status = "cancelled"
                await db.commit()
        except Exception as e:
            print(f"Error checking missed payment for order {order.id}: {e}")
            await db.rollback()
        finally:
            await asyncio.sleep(0.05)


async def reconcile_pending_refunds(db: AsyncSession):
    """
    Finds orders that are stuck in 'refund_initiated' and checks their refund status on Razorpay.
    """
    settings = get_settings()
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        return

    stmt = select(Order).where(
        Order.payment_status == "refund_initiated",
        Order.refund_id != None
    )
    result = await db.execute(stmt)
    pending_refunds = result.scalars().all()
    
    if not pending_refunds:
        return
        
    print(f"DEBUG: Found {len(pending_refunds)} pending refunds. Checking Razorpay...")
    client = _get_razorpay_client(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET, timeout=5)

    for order in pending_refunds:
        try:
            refund = await asyncio.to_thread(client.refund.fetch, order.refund_id)
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
        finally:
            await asyncio.sleep(0.05)
