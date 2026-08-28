import asyncio
import razorpay
from datetime import datetime, timezone
from sqlalchemy import select

from app.database.session import async_session_factory
from app.models.order import Order
from app.core.config import get_settings

async def fix_settled_at():
    settings = get_settings()
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        print("No Razorpay credentials found.")
        return

    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

    async with async_session_factory() as db:
        # Find all settled orders
        result = await db.execute(
            select(Order).where(Order.settlement_status == 'settled')
        )
        orders = result.scalars().all()
        
        print(f"Found {len(orders)} settled orders to check.")
        updated_count = 0
        
        for order in orders:
            print(order)
            try:
                unix_time = None
                recipient_account = None
                settlement_id = None
                
                if order.razorpay_transfer_id:
                    transfer = client.transfer.fetch(order.razorpay_transfer_id)
                    recipient_account = transfer.get("recipient")
                    settlement_id = transfer.get("recipient_settlement_id") or transfer.get("settlement_id")
                    unix_time = transfer.get("processed_at") or transfer.get("created_at")
                    
                elif order.payment_session_id and order.payment_session_id.startswith('pay_'):
                    transfers = client.payment.transfers(order.payment_session_id)
                    if transfers and "items" in transfers and len(transfers["items"]) > 0:
                        transfer = transfers["items"][0]
                        recipient_account = transfer.get("recipient")
                        settlement_id = transfer.get("recipient_settlement_id") or transfer.get("settlement_id")
                        unix_time = transfer.get("processed_at") or transfer.get("created_at")
                
                # If we have a settlement ID and recipient, fetch the ACTUAL settlement date (when the money hits the bank)
                if settlement_id and recipient_account:
                    import requests
                    from requests.auth import HTTPBasicAuth
                    url = f"https://api.razorpay.com/v1/settlements/{settlement_id}"
                    resp = requests.get(
                        url, 
                        headers={"X-Razorpay-Account": recipient_account},
                        auth=HTTPBasicAuth(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
                    )
                    if resp.status_code == 200:
                        actual_settlement = resp.json()
                        unix_time = actual_settlement.get("created_at") or unix_time
                        
                if unix_time:
                    real_time = datetime.fromtimestamp(unix_time, timezone.utc)
                    print(f"Order {order.id}: Updated settled_at to {real_time}")
                    if order.settled_at != real_time:
                        order.settled_at = real_time
                        updated_count += 1
            except Exception as e:
                print(f"Failed to fetch Razorpay data for order {order.id}: {e}")
                
        if updated_count > 0:
            await db.commit()
            print(f"Successfully updated {updated_count} orders.")
        else:
            print("No updates needed.")

if __name__ == "__main__":
    asyncio.run(fix_settled_at())
