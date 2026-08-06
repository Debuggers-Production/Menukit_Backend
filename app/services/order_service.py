"""Order management service."""

import uuid
import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.order import Order, OrderItem
from app.models.shop import Shop
from app.models.shop_settings import ShopSettings
from app.schemas.order import OrderCreate


def get_customer_user_id(phone: str) -> str:
    clean = "".join(filter(str.isdigit, phone))
    if len(clean) > 10:
        clean = clean[-10:]
    hash1 = 5381
    hash2 = 0
    for char in clean:
        code = ord(char)
        hash1 = ((hash1 * 33) ^ code) & 0xFFFFFFFF
        hash2 = (((hash2 << 5) - hash2) + code) & 0xFFFFFFFF
    return f"usr_{hash1:08x}{hash2:08x}"


class OrderService:
    """Handles ordering logic and Cashfree Payment Gateway integration."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_order(self, shop_id: uuid.UUID, data: OrderCreate) -> Order:
        """Create a new customer order and initialize payment session if online."""
        # 1. Fetch shop and settings
        result = await self.db.execute(select(Shop).where(Shop.id == shop_id))
        shop = result.scalar_one_or_none()
        if not shop:
            raise HTTPException(status_code=404, detail="Restaurant not found")

        settings_result = await self.db.execute(select(ShopSettings).where(ShopSettings.shop_id == shop.id))
        settings = settings_result.scalar_one_or_none()
        if not settings:
            raise HTTPException(status_code=400, detail="Ordering is not configured for this restaurant")

        # 2. Check channel availability
        if data.order_type == "delivery" and not settings.delivery_enabled:
            raise HTTPException(status_code=400, detail="Delivery option is not available")
        if data.order_type == "takeaway" and not settings.takeaway_enabled:
            raise HTTPException(status_code=400, detail="Takeaway option is not available")
        if data.order_type == "dine_in" and not settings.dinein_enabled:
            raise HTTPException(status_code=400, detail="Dine-in option is not available")

        # 3. Determine status
        initial_status = "accepted" if settings.auto_accept_orders else "pending"

        # 1. Validate that all menu items exist in the database
        from app.models.menu_item import MenuItem
        menu_item_ids = [it.menu_item_id for it in data.items]
        from app.models.category import Category
        result = await self.db.execute(
            select(MenuItem).join(Category).where(
                MenuItem.id.in_(menu_item_ids),
                MenuItem.is_available == True,
                Category.is_active == True
            )
        )
        existing_items = result.scalars().all()
        existing_ids = {item.id for item in existing_items}

        for it in data.items:
            if it.menu_item_id not in existing_ids:
                raise HTTPException(
                    status_code=400,
                    detail=f"Item '{it.name}' is no longer available. Please remove it from your cart and try again."
                )

        # 2. Update customer's saved delivery address if provided
        if data.order_type == "delivery" and data.delivery_address:
            from app.models.customer import Customer
            phone_variants = [data.customer_phone]
            if data.customer_phone.startswith("+91"):
                phone_variants.append(data.customer_phone[3:])
            else:
                phone_variants.append("+91" + data.customer_phone)

            cust_result = await self.db.execute(
                select(Customer).where(Customer.mobile_number.in_(phone_variants))
            )
            customer = cust_result.scalars().first()
            if customer:
                customer.delivery_address = data.delivery_address

        # 3. Create OrderItem instances
        order_id = uuid.uuid4()
        items_list = []
        for it in data.items:
            item = OrderItem(
                id=uuid.uuid4(),
                order_id=order_id,
                menu_item_id=it.menu_item_id,
                name=it.name,
                quantity=it.quantity,
                price=it.price,
                variant_info=it.variant_info,
                addons_info=it.addons_info,
            )
            items_list.append(item)

        # 4. Create Order model instance
        order = Order(
            id=order_id,
            shop_id=shop.id,
            customer_name=data.customer_name,
            customer_phone=data.customer_phone,
            order_type=data.order_type,
            table_number=data.table_number,
            delivery_address=data.delivery_address,
            order_status=initial_status,
            payment_status="pending",
            payment_method=data.payment_method,
            total_amount=data.total_amount,
            items=items_list,
        )
        self.db.add(order)

        # Create notification for merchant (for non-online payment methods like cash/upi)
        if data.payment_method != "online":
            from app.services.notification_service import NotificationService
            notif_service = NotificationService(self.db)
            await notif_service.create_notification(
                shop_id=shop.id,
                type="NEW_ORDER",
                title="New Order Received",
                message=f"New order #{order.id.hex[:8]} placed by {order.customer_name} ({order.order_type})",
                metadata={"order_id": str(order.id)}
            )

        await self.db.flush()
        
        # Automatically award 0.15 contest credits if order total >= ₹100
        if float(order.total_amount) >= 100.0:
            await self._award_contest_credits_if_eligible(order)

        return order

    async def initiate_order_payment(self, order: Order) -> Order:
        from app.models.shop_settings import ShopSettings
        import httpx

        settings_result = await self.db.execute(select(ShopSettings).where(ShopSettings.shop_id == order.shop_id))
        settings = settings_result.scalar_one_or_none()
        if not settings or not settings.cashfree_app_id or not settings.cashfree_secret_key:
            raise HTTPException(
                status_code=400, 
                detail="Online payments are currently unavailable. Please select Pay at Counter / Cash."
            )

        cashfree_base_url = (
            "https://sandbox.cashfree.com/pg"
            if settings.cashfree_sandbox
            else "https://api.cashfree.com/pg"
        )
        headers = {
            "x-client-id": settings.cashfree_app_id,
            "x-client-secret": settings.cashfree_secret_key,
            "x-api-version": "2023-08-01",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        clean_phone = "".join(filter(str.isdigit, order.customer_phone))
        if len(clean_phone) > 10:
            clean_phone = clean_phone[-10:]

        link_id = f"link_order_{order.id.hex[:12]}_{uuid.uuid4().hex[:4]}"
        payload = {
            "link_id": link_id,
            "link_amount": float(order.total_amount),
            "link_currency": "INR",
            "customer_details": {
                "customer_phone": clean_phone,
                "customer_id": f"cust_{clean_phone}",
                "customer_name": order.customer_name
            },
            "link_meta": {
                "return_url": f"https://menukit.debuggers.co.in/shop/{order.shop_id}/order/{order.id}?payment_success=true&link_id={link_id}"
            },
            "link_purpose": f"Order Payment #{order.id.hex[:6].upper()}"
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(f"{cashfree_base_url}/links", json=payload, headers=headers)
                if resp.status_code != 200:
                    print(f"Cashfree failed status: {resp.status_code}, body: {resp.text}")
                    raise HTTPException(
                        status_code=502, 
                        detail=f"Failed to create online payment link: {resp.text}"
                    )
                res_data = resp.json()
                order.payment_session_id = res_data.get("link_url")
                order.cashfree_order_id = link_id
                order.payment_method = "online"
                self.db.add(order)
                await self.db.flush()
                return order
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Failed to connect to Cashfree payment server: {str(e)}")

    async def verify_payment(self, order_id: uuid.UUID) -> Order:
        """Query Cashfree to verify customer payment status."""
        result = await self.db.execute(
            select(Order).options(selectinload(Order.items)).where(Order.id == order_id)
        )
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        if order.payment_method != "online" or not order.cashfree_order_id:
            return order

        settings_result = await self.db.execute(select(ShopSettings).where(ShopSettings.shop_id == order.shop_id))
        settings = settings_result.scalar_one_or_none()
        if not settings or not settings.cashfree_app_id or not settings.cashfree_secret_key:
            return order

        # Query Cashfree Order/Link Status
        is_link = order.cashfree_order_id.startswith("link_order_") or order.cashfree_order_id.startswith("link_")

        if is_link:
            cashfree_url = (
                f"https://sandbox.cashfree.com/pg/links/{order.cashfree_order_id}"
                if settings.cashfree_sandbox
                else f"https://api.cashfree.com/pg/links/{order.cashfree_order_id}"
            )
        else:
            cashfree_url = (
                f"https://sandbox.cashfree.com/pg/orders/{order.cashfree_order_id}"
                if settings.cashfree_sandbox
                else f"https://api.cashfree.com/pg/orders/{order.cashfree_order_id}"
            )

        headers = {
            "x-client-id": settings.cashfree_app_id,
            "x-client-secret": settings.cashfree_secret_key,
            "x-api-version": "2023-08-01",
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(cashfree_url, headers=headers)
                if resp.status_code == 200:
                    res_data = resp.json()
                    if is_link:
                        cf_status = res_data.get("link_status")
                        if cf_status == "PAID":
                            order.payment_status = "paid"
                        elif cf_status in ["CANCELLED", "EXPIRED"]:
                            order.payment_status = "failed"
                    else:
                        cf_status = res_data.get("order_status")
                        if cf_status == "PAID":
                            order.payment_status = "paid"
                        elif cf_status in ["FAILED", "EXPIRED"]:
                            order.payment_status = "failed"
        except Exception as e:
            print(f"Error verifying payment: {str(e)}")

        # Broadcast payment status update via WebSocket
        from app.services.websocket_manager import customer_manager
        ws_msg = {
            "type": "order_update",
            "order_id": str(order.id),
            "status": order.order_status,
            "payment_status": order.payment_status,
            "customer_phone": order.customer_phone
        }
        await customer_manager.broadcast_to_customer(order.customer_phone, ws_msg)
        
        clean_phone = "".join(filter(str.isdigit, order.customer_phone))
        if len(clean_phone) > 10:
            clean_phone = clean_phone[-10:]
        if clean_phone != order.customer_phone:
            await customer_manager.broadcast_to_customer(clean_phone, ws_msg)

        # Broadcast to hashed customer user ID
        user_id = get_customer_user_id(clean_phone)
        await customer_manager.broadcast_to_customer(user_id, ws_msg)

        return order

    async def get_order_by_id(self, order_id: uuid.UUID) -> Order:
        """Fetch a specific order."""
        result = await self.db.execute(
            select(Order).options(selectinload(Order.items)).where(Order.id == order_id)
        )
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        return order

    async def get_shop_orders(self, shop_id: uuid.UUID) -> list[Order]:
        """Fetch all orders placed in a shop, sorted by creation date."""
        result = await self.db.execute(
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.shop_id == shop_id)
            .order_by(Order.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_orders_by_user(self, user_id: uuid.UUID) -> list[Order]:
        """Fetch all orders for a merchant's shop based on user ID."""
        # Find shop first
        result = await self.db.execute(select(Shop).where(Shop.user_id == user_id))
        shop = result.scalar_one_or_none()
        if not shop:
            raise HTTPException(status_code=404, detail="Shop not found")
        return await self.get_shop_orders(shop.id)

    async def update_payment_status(self, order_id: uuid.UUID, payment_status: str, user_id: uuid.UUID) -> Order:
        """Update the payment status of an order (merchant only). If 'refunded' and paid online, triggers Cashfree refund."""
        from app.models.shop_settings import ShopSettings
        import httpx
        result = await self.db.execute(select(Shop).where(Shop.user_id == user_id))
        shop = result.scalar_one_or_none()
        if not shop:
            raise HTTPException(status_code=403, detail="Not authorized")

        order = await self.get_order_by_id(order_id)
        if order.shop_id != shop.id:
            raise HTTPException(status_code=403, detail="Not authorized")

        # Auto-refund via Cashfree if marking as refunded and payment was online
        if payment_status == "refunded" and order.payment_method == "online" and order.cashfree_order_id:
            settings_result = await self.db.execute(
                select(ShopSettings).where(ShopSettings.shop_id == shop.id)
            )
            settings = settings_result.scalar_one_or_none()

            if settings and settings.cashfree_app_id and settings.cashfree_secret_key:
                cashfree_base = (
                    "https://sandbox.cashfree.com/pg"
                    if settings.cashfree_sandbox
                    else "https://api.cashfree.com/pg"
                )
                headers = {
                    "x-client-id": settings.cashfree_app_id,
                    "x-client-secret": settings.cashfree_secret_key,
                    "x-api-version": "2023-08-01",
                    "Content-Type": "application/json",
                }
                refund_payload = {
                    "refund_amount": float(order.total_amount),
                    "refund_id": f"refund_{order.id.hex[:12]}",
                    "refund_note": "Order cancelled — full refund by merchant",
                }
                try:
                    async with httpx.AsyncClient(timeout=15.0) as client:
                        resp = await client.post(
                            f"{cashfree_base}/orders/{order.cashfree_order_id}/refunds",
                            json=refund_payload,
                            headers=headers,
                        )
                        if resp.status_code not in (200, 201):
                            raise HTTPException(
                                status_code=502,
                                detail=f"Cashfree refund failed: {resp.text}"
                            )
                except httpx.RequestError as e:
                    raise HTTPException(status_code=502, detail=f"Could not reach Cashfree: {str(e)}")

        order.payment_status = payment_status
        return order

    async def update_order_status(self, order_id: uuid.UUID, status: str, user_id: uuid.UUID) -> Order:
        """Update the status of an order (merchant only)."""
        # Ensure shop belongs to merchant
        result = await self.db.execute(select(Shop).where(Shop.user_id == user_id))
        shop = result.scalar_one_or_none()
        if not shop:
            raise HTTPException(status_code=403, detail="Not authorized")

        order = await self.get_order_by_id(order_id)
        if order.shop_id != shop.id:
            raise HTTPException(status_code=403, detail="Not authorized")

        order.order_status = status
        
        # Award 0.15 Contest Credits if completed order total >= ₹100
        if status.lower() == "completed":
            await self._award_contest_credits_if_eligible(order)

        # Trigger notification log
        from app.models.activity_log import ActivityLog
        log = ActivityLog(
            id=uuid.uuid4(),
            user_id=user_id,
            action=f"order_{status}",
            details=f"Order {order.id} status updated to {status}."
        )
        self.db.add(log)

        # Create notification for order status update
        from app.services.notification_service import NotificationService
        notif_service = NotificationService(self.db)
        await notif_service.create_notification(
            shop_id=shop.id,
            type="ORDER_STATUS",
            title=f"Order #{order.id.hex[:8]} {status.capitalize()}",
            message=f"Order status has been updated to {status}.",
            metadata={"order_id": str(order.id), "status": status}
        )

        # Broadcast to customer live instantly via WebSocket
        from app.services.websocket_manager import customer_manager
        ws_msg = {
            "type": "order_update",
            "order_id": str(order.id),
            "status": order.order_status,
            "payment_status": order.payment_status,
            "customer_phone": order.customer_phone
        }
        await customer_manager.broadcast_to_customer(order.customer_phone, ws_msg)
        
        clean_phone = "".join(filter(str.isdigit, order.customer_phone))
        if len(clean_phone) > 10:
            clean_phone = clean_phone[-10:]
        if clean_phone != order.customer_phone:
            await customer_manager.broadcast_to_customer(clean_phone, ws_msg)

        # Broadcast to hashed customer user ID
        user_id = get_customer_user_id(clean_phone)
        await customer_manager.broadcast_to_customer(user_id, ws_msg)

        return order
    async def _award_contest_credits_if_eligible(self, order: Order):
        """Award 0.15 contest credits if order total >= ₹100."""
        if not order or getattr(order, "credits_rewarded", False):
            return
        if float(order.total_amount or 0.0) >= 100.0 and order.customer_phone:
            from app.models.customer import Customer
            from app.models.contest import ContestCredit
            
            clean_phone = "".join(filter(str.isdigit, order.customer_phone))
            if len(clean_phone) > 10:
                clean_phone = clean_phone[-10:]
            c_res = await self.db.execute(select(Customer).where(Customer.mobile_number.like(f"%{clean_phone}")))
            customer = c_res.scalars().first()

            # Auto-create Customer record if not created yet
            if not customer:
                customer = Customer(
                    shop_id=order.shop_id,
                    name=order.customer_name or "Guest",
                    mobile_number=order.customer_phone,
                    is_auto_registered=True
                )
                self.db.add(customer)
                await self.db.flush()

            if customer:
                cc_res = await self.db.execute(select(ContestCredit).where(ContestCredit.customer_id == customer.id))
                credit = cc_res.scalar_one_or_none()
                if not credit:
                    credit = ContestCredit(customer_id=customer.id, credits=0.15)
                    self.db.add(credit)
                else:
                    credit.credits = round(float(credit.credits) + 0.15, 2)
                order.credits_rewarded = True
        
