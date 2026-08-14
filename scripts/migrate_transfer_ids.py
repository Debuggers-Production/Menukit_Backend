"""One-time script to migrate Razorpay transfer IDs for existing unsettled orders."""

import asyncio
from sqlalchemy import select, update
import razorpay

from app.core.config import get_settings
from app.database.session import async_session_factory
from app.models.order import Order


async def migrate_transfer_ids():
    settings = get_settings()

    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        print("Skipping migration: Razorpay credentials not configured.")
        return

    # Find paid orders without razorpay_transfer_id and having a valid payment session ID
    async with async_session_factory() as db:
        stmt = select(Order).where(
            Order.payment_status == "paid",
            Order.payment_session_id != None,
            Order.razorpay_transfer_id == None,
            Order.razorpay_order_id != None,
            ~Order.razorpay_order_id.startswith("order_mock_")
        )
        
        result = await db.execute(stmt)
        orders = result.scalars().all()
        
        if not orders:
            print("No orders need transfer ID migration.")
            return

        print(f"Found {len(orders)} orders missing razorpay_transfer_id. Migrating...")
        
        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

        migrated_count = 0
        for order in orders:
            try:
                print(f"Fetching transfers for payment_id {order.payment_session_id} (order {order.id})")
                transfers = client.transfer.all({'payment_id': order.payment_session_id})
                
                if transfers and 'items' in transfers and len(transfers['items']) > 0:
                    transfer_id = transfers['items'][0]['id']
                    
                    await db.execute(
                        update(Order)
                        .where(Order.id == order.id)
                        .values(razorpay_transfer_id=transfer_id)
                    )
                    await db.commit()
                    print(f"Successfully migrated order {order.id} with transfer ID {transfer_id}")
                    migrated_count += 1
                else:
                    print(f"No transfers found for payment_id {order.payment_session_id} (order {order.id})")
            except Exception as e:
                print(f"Error migrating order {order.id}: {e}")
                await db.rollback()
                
        print(f"Migration complete. {migrated_count} orders updated.")

if __name__ == "__main__":
    asyncio.run(migrate_transfer_ids())
