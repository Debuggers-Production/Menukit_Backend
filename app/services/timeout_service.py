import asyncio
from datetime import datetime, timezone
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.order import Order
from app.database.session import async_session_factory

async def process_payment_timeouts():
    """Finds orders that are PAYMENT_PENDING and past their expiry time, marking them CANCELLED."""
    while True:
        try:
            async with async_session_factory() as db:
                now = datetime.now(timezone.utc)
                
                # We use version column for optimistic concurrency control
                stmt = select(Order).where(
                    Order.order_status == "PAYMENT_PENDING",
                    Order.payment_expires_at != None,
                    Order.payment_expires_at <= now
                )
                result = await db.execute(stmt)
                expired_orders = result.scalars().all()
                
                for order in expired_orders:
                    # Update order using OCC to ensure we don't race with a payment webhook
                    update_stmt = (
                        update(Order)
                        .where(
                            Order.id == order.id,
                            Order.version == order.version,
                            Order.order_status == "PAYMENT_PENDING"
                        )
                        .values(
                            order_status="CANCELLED",
                            cancellation_reason="PAYMENT_TIMEOUT",
                            version=Order.version + 1
                        )
                    )
                    res = await db.execute(update_stmt)
                    if res.rowcount > 0:
                        print(f"DEBUG: Order {order.id} timed out. Marked as CANCELLED.")
                        
                        # Restore any discount redemptions / customer discount codes used in this order
                        from app.services.order_service import OrderService
                        order_svc = OrderService(db)
                        await order_svc._restore_discount_usages_for_order(order)

                        # Broadcast to customer and shop
                        from app.services.websocket_manager import customer_manager, manager
                        from app.services.order_service import get_customer_user_id
                        ws_msg = {
                            "type": "order_update",
                            "order_id": str(order.id),
                            "status": "CANCELLED",
                            "cancellation_reason": "PAYMENT_TIMEOUT"
                        }
                        
                        # Customer
                        if order.customer_phone:
                            clean_phone = "".join(filter(str.isdigit, order.customer_phone))
                            customer_ws_id = get_customer_user_id(clean_phone)
                            await customer_manager.broadcast_to_customer(customer_ws_id, ws_msg)
                                
                        # Vendor
                        await manager.broadcast_to_shop(str(order.shop_id), ws_msg)
                        
                # Also sweep & restore any active discount redemptions attached to CANCELLED or REJECTED orders
                from app.models.discount import DiscountRedemption, CustomerDiscountCode
                from sqlalchemy import func
                stale_redemptions_stmt = (
                    select(DiscountRedemption)
                    .join(Order, DiscountRedemption.order_id == Order.id)
                    .where(
                        DiscountRedemption.status == "active",
                        func.lower(Order.order_status).in_(["cancelled", "rejected"])
                    )
                )
                stale_res = await db.execute(stale_redemptions_stmt)
                stale_redemptions = stale_res.scalars().all()
                for sr in stale_redemptions:
                    sr.status = "restored"
                    if sr.customer_identifier:
                        raw_c = str(sr.customer_identifier).strip()
                        clean_c = "".join(filter(str.isdigit, raw_c))
                        pv = {raw_c, clean_c}
                        if len(clean_c) >= 10:
                            pv.add(clean_c[-10:])
                            pv.add(f"+91{clean_c[-10:]}")
                            pv.add(f"91{clean_c[-10:]}")
                        await db.execute(
                            update(CustomerDiscountCode)
                            .where(
                                CustomerDiscountCode.shop_id == sr.shop_id,
                                CustomerDiscountCode.discount_id == sr.discount_id,
                                CustomerDiscountCode.customer_identifier.in_(list(pv))
                            )
                            .values(is_redeemed=False, redeemed_at=None)
                        )

                await db.commit()
        except Exception as e:
            print(f"Error in payment timeout job: {e}")
        finally:
            # Poll every 10 seconds for strict 5-minute timeout enforcement
            await asyncio.sleep(10)
