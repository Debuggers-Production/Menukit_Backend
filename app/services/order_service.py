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
from typing import List, Optional, Any


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
        if settings.auto_accept_orders:
            # For cash orders with auto-accept, set directly to ACCEPTED (paid on delivery/counter)
            if data.payment_method in ["cash", "cash_on_delivery", "counter"]:
                initial_status = "ACCEPTED"
            else:
                initial_status = "PAYMENT_PENDING"
        else:
            # Standard initial status requires vendor acceptance
            initial_status = "PENDING_VENDOR"

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

        # 2. Customer Lookup & Auto-Link/Create
        customer = None
        if data.customer_phone and data.customer_phone.strip():
            raw_phone = data.customer_phone.strip()
            clean_phone = "".join(filter(str.isdigit, raw_phone))
            if clean_phone:
                phone_variants = [raw_phone, clean_phone]
                if len(clean_phone) == 10:
                    phone_variants.extend([f"+91{clean_phone}", f"91{clean_phone}"])
                elif len(clean_phone) == 12 and clean_phone.startswith("91"):
                    phone_variants.extend([clean_phone[2:], f"+{clean_phone}"])

                from app.models.customer import Customer
                from app.models.membership import CustomerRetailerMembership

                cust_stmt = select(Customer).where(Customer.mobile_number.in_(phone_variants))
                cust_res = await self.db.execute(cust_stmt)
                customer = cust_res.scalars().first()

                cust_name = data.customer_name.strip() if (data.customer_name and data.customer_name.strip() not in ["Walk-in", "Walk-in Customer", ""]) else None

                if customer:
                    # Update name if previously empty/generic and a valid name is provided
                    if cust_name and (not customer.name or customer.name in ["Walk-in", "Customer"]):
                        customer.name = cust_name
                    if data.order_type == "delivery" and data.delivery_address:
                        customer.delivery_address = data.delivery_address
                else:
                    # Standardize new customer phone number (e.g. +91 prefix for 10-digit Indian numbers)
                    standard_mobile = f"+91{clean_phone}" if len(clean_phone) == 10 else (f"+{clean_phone}" if len(clean_phone) == 12 and clean_phone.startswith("91") else raw_phone)
                    customer = Customer(
                        id=uuid.uuid4(),
                        name=cust_name or "Customer",
                        mobile_number=standard_mobile,
                        delivery_address=data.delivery_address if data.order_type == "delivery" else None
                    )
                    self.db.add(customer)
                    await self.db.flush()

                # Ensure customer is linked to this shop as a member
                mem_stmt = select(CustomerRetailerMembership).where(
                    CustomerRetailerMembership.customer_id == customer.id,
                    CustomerRetailerMembership.shop_id == shop.id
                )
                mem_res = await self.db.execute(mem_stmt)
                membership = mem_res.scalar_one_or_none()
                if not membership:
                    membership = CustomerRetailerMembership(
                        id=uuid.uuid4(),
                        customer_id=customer.id,
                        shop_id=shop.id,
                        is_retailer_added=True
                    )
                    self.db.add(membership)

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
        from datetime import datetime, timezone, timedelta
        
        initial_pay_status = (getattr(data, "payment_status", None) or "pending").lower()
        
        # Normalize order customer_phone to match customer profile format
        order_phone = ""
        if customer and customer.mobile_number:
            order_phone = customer.mobile_number
        elif data.customer_phone and data.customer_phone.strip():
            cp_digits = "".join(filter(str.isdigit, data.customer_phone))
            order_phone = f"+91{cp_digits}" if len(cp_digits) == 10 else data.customer_phone.strip()

        order = Order(
            id=order_id,
            shop_id=shop.id,
            customer_name=data.customer_name or "Walk-in",
            customer_phone=order_phone,
            order_type=data.order_type,
            table_number=data.table_number,
            delivery_address=data.delivery_address,
            order_status=initial_status,
            payment_status=initial_pay_status,
            payment_method=data.payment_method,
            total_amount=data.total_amount,
            items=items_list,
        )

        
        if initial_status == "PAYMENT_PENDING" and initial_pay_status != "paid" and data.payment_method not in ["cash", "cash_on_delivery", "counter"]:
            order.payment_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
            
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
        
        # Automatically award 0.15 contest credits if order total >= ₹100 for non-online orders
        if data.payment_method != "online" and float(order.total_amount) >= 100.0:
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

    async def get_shop_orders(
        self,
        shop_id: uuid.UUID,
        skip: int = 0,
        limit: int = 20,
        status_filter: Optional[str] = "all",
        type_filter: Optional[str] = "all",
        search: Optional[str] = None,
        date_filter: Optional[str] = None
    ) -> tuple[list[Order], int, bool]:
        """Fetch shop orders with SQL filtering, search, date filter, and pagination."""
        from sqlalchemy import func, or_, and_, cast, String
        conditions = [Order.shop_id == shop_id]

        if status_filter and status_filter != "all":
            if status_filter == "new":
                conditions.append(Order.order_status.in_(["PENDING_VENDOR", "pending"]))
            elif status_filter == "awaiting_payment":
                # Takeaway & online/delivery orders waiting for payment
                conditions.append(
                    and_(
                        Order.order_status.in_(["PAYMENT_PENDING"]),
                        Order.order_type != "dine_in"
                    )
                )
            elif status_filter in ["preparing", "awaiting_complete", "accepted"]:
                # Awaiting complete includes accepted dine-in orders (guests eat first) and paid takeaway/delivery orders
                conditions.append(
                    or_(
                        Order.order_status.in_(["PAID", "accepted", "ACCEPTED", "PREPARING", "READY"]),
                        and_(
                            Order.order_type == "dine_in",
                            Order.order_status.in_(["PAYMENT_PENDING", "ACCEPTED", "accepted"])
                        )
                    )
                )
            elif status_filter == "completed":
                conditions.append(Order.order_status.in_(["DELIVERED", "COMPLETED", "completed"]))
            elif status_filter == "cancelled":
                conditions.append(Order.order_status.in_(["CANCELLED", "OUT_FOR_DELIVERY", "rejected", "cancelled"]))

        if type_filter and type_filter != "all":
            conditions.append(Order.order_type == type_filter)

        if date_filter and date_filter.strip():
            try:
                from datetime import datetime, date, time
                d = date.fromisoformat(date_filter.strip())
                start_dt = datetime.combine(d, time.min)
                end_dt = datetime.combine(d, time.max)
                conditions.append(
                    or_(
                        func.date(Order.created_at) == d,
                        (Order.created_at >= start_dt) & (Order.created_at <= end_dt)
                    )
                )
            except ValueError:
                pass

        if search and search.strip():
            term = f"%{search.strip()}%"
            conditions.append(
                or_(
                    Order.customer_name.ilike(term),
                    Order.customer_phone.ilike(term),
                    cast(Order.id, String).ilike(term),
                    Order.table_number.ilike(term),
                    Order.delivery_address.ilike(term)
                )
            )

        total_count_q = await self.db.execute(select(func.count(Order.id)).where(*conditions))
        total_count = total_count_q.scalar() or 0

        result = await self.db.execute(
            select(Order)
            .options(selectinload(Order.items))
            .where(*conditions)
            .order_by(Order.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        orders = list(result.scalars().all())
        has_more = (skip + len(orders)) < total_count

        return orders, total_count, has_more

    async def get_status_counts(self, shop_id: uuid.UUID, date_filter: Optional[str] = None) -> dict[str, int]:
        """Calculate shop-wide counts for each status tab, optionally filtered by date."""
        from sqlalchemy import func, or_
        conditions = [Order.shop_id == shop_id]

        if date_filter and date_filter.strip():
            try:
                from datetime import datetime, date, time
                d = date.fromisoformat(date_filter.strip())
                start_dt = datetime.combine(d, time.min)
                end_dt = datetime.combine(d, time.max)
                conditions.append(
                    or_(
                        func.date(Order.created_at) == d,
                        (Order.created_at >= start_dt) & (Order.created_at <= end_dt)
                    )
                )
            except ValueError:
                pass

        stmt = (
            select(Order.order_status, Order.order_type, func.count(Order.id))
            .where(*conditions)
            .group_by(Order.order_status, Order.order_type)
        )
        result = await self.db.execute(stmt)
        rows = result.all()

        new_count = 0
        awaiting_payment_count = 0
        awaiting_complete_count = 0
        completed_count = 0
        cancelled_count = 0
        all_count = 0

        for status_val, order_type_val, count_val in rows:
            all_count += count_val
            s = (status_val or "").upper()
            t = (order_type_val or "").lower()

            if s in ["PENDING_VENDOR", "PENDING"]:
                new_count += count_val
            elif s == "PAYMENT_PENDING":
                if t == "dine_in":
                    # Dine-in accepted orders are active tickets awaiting completion
                    awaiting_complete_count += count_val
                else:
                    awaiting_payment_count += count_val
            elif s in ["PAID", "ACCEPTED", "PREPARING", "READY"]:
                awaiting_complete_count += count_val
            elif s in ["DELIVERED", "COMPLETED"]:
                completed_count += count_val
            elif s in ["CANCELLED", "OUT_FOR_DELIVERY", "REJECTED"]:
                cancelled_count += count_val

        return {
            "all": all_count,
            "new": new_count,
            "awaiting_payment": awaiting_payment_count,
            "accepted": awaiting_complete_count,
            "preparing": awaiting_complete_count,
            "awaiting_complete": awaiting_complete_count,
            "completed": completed_count,
            "cancelled": cancelled_count,
        }




    async def get_orders_by_user(self, user_id: uuid.UUID) -> list[Order]:
        """Fetch all orders for a merchant's shop based on user ID."""
        # Find shop first
        result = await self.db.execute(select(Shop).where(Shop.user_id == user_id))
        shop = result.scalar_one_or_none()
        if not shop:
            raise HTTPException(status_code=404, detail="Shop not found")
        return await self.get_shop_orders(shop.id)

    async def update_payment_status(self, order_id: uuid.UUID, payment_status: str, shop_id: uuid.UUID) -> Order:
        """Update the payment status of an order (merchant only). If 'refunded' and paid online, triggers Cashfree refund."""
        from app.models.shop_settings import ShopSettings
        import httpx
        
        # Verify order belongs to shop
        order = await self.get_order_by_id(order_id)
        if order.shop_id != shop_id:
            raise HTTPException(status_code=403, detail="Not authorized")

        # Auto-refund via Cashfree if marking as refunded and payment was online
        if payment_status == "refunded" and order.payment_method == "online" and order.cashfree_order_id:
            settings_result = await self.db.execute(
                select(ShopSettings).where(ShopSettings.shop_id == shop_id)
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
        
        # If manually marked as paid, advance the order status automatically
        if payment_status.lower() == "paid" and order.order_status == "PAYMENT_PENDING":
            order.order_status = "PAID"
            order.payment_expires_at = None
            await self._send_order_status_whatsapp_notification(order)
            
        return order

    async def update_order_status(self, order_id: uuid.UUID, status: str, shop_id: uuid.UUID, cancellation_reason: str = None, user_id: Optional[uuid.UUID] = None) -> Order:
        """Update the status of an order (merchant only)."""
        
        order = await self.get_order_by_id(order_id)
        if order.shop_id != shop_id:
            raise HTTPException(status_code=403, detail="Not authorized")

        current_status = order.order_status
        status = status.upper()

        valid_transitions = {
            "PENDING_VENDOR": ["PAYMENT_PENDING", "ACCEPTED", "CANCELLED"],
            "PAYMENT_PENDING": ["PAID", "ACCEPTED", "CANCELLED"],
            "PAID": ["PREPARING", "ACCEPTED", "CANCELLED"],
            "ACCEPTED": ["PREPARING", "READY", "DELIVERED", "COMPLETED", "CANCELLED"],
            "PREPARING": ["READY", "OUT_FOR_DELIVERY", "DELIVERED", "COMPLETED", "CANCELLED"],
            "READY": ["OUT_FOR_DELIVERY", "DELIVERED", "COMPLETED", "CANCELLED"],
            "OUT_FOR_DELIVERY": ["DELIVERED", "COMPLETED", "CANCELLED"],
            # Fallbacks for legacy/current app usage:
            "PENDING": ["ACCEPTED", "REJECTED", "CANCELLED", "PAYMENT_PENDING"],
        }

        
        # We don't enforce strict transitions if current_status is not in our map (legacy)
        # But we do enforce payment checks for takeaway/delivery
        if status == "PREPARING" and order.payment_status.lower() != "paid" and order.payment_method.lower() != "cash" and order.order_type != "dine_in":
            raise HTTPException(status_code=400, detail="Cannot start preparation until payment is confirmed.")


        order.order_status = status
        
        if status == "PAYMENT_PENDING" and order.payment_method not in ["cash", "cash_on_delivery", "counter"]:
            from datetime import timedelta, datetime, timezone
            order.payment_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        else:
            # Clear expiry if we move past PAYMENT_PENDING or for cash orders
            order.payment_expires_at = None
        
        if status == "CANCELLED":
            order.cancellation_reason = cancellation_reason or order.cancellation_reason or "VENDOR_REJECTED"

        # Award 0.15 Contest Credits if completed order total >= ₹100
        if status in ["COMPLETED", "DELIVERED"]:
            await self._award_contest_credits_if_eligible(order)

        # Trigger notification log if user_id present
        if user_id:
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
            shop_id=shop_id,
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
            "customer_phone": order.customer_phone,
            "payment_expires_at": order.payment_expires_at.isoformat() if order.payment_expires_at else None
        }
        
        # Broadcast to hashed customer user ID
        clean_phone = "".join(filter(str.isdigit, order.customer_phone))
        customer_ws_id = get_customer_user_id(clean_phone)
        await customer_manager.broadcast_to_customer(customer_ws_id, ws_msg)

        # Broadcast to hashed customer user ID
        user_id = get_customer_user_id(clean_phone)
        await customer_manager.broadcast_to_customer(user_id, ws_msg)

        # Send WhatsApp template notification 'menukit_order_create' to customer
        await self._send_order_status_whatsapp_notification(order)

        return order

    async def _send_order_status_whatsapp_notification(self, order: Order, shop_name: Optional[str] = None):
        """Send 'menukit_order_created' WhatsApp template to customer ONLY when order is BOTH Completed AND Paid."""
        if not order or not order.customer_phone:
            return

        # STRICT GUARD: Only send WhatsApp message if order is BOTH Completed AND Paid
        is_paid = str(order.payment_status or "").lower() == "paid"
        is_completed = str(order.order_status or "").upper() in ["COMPLETED", "DELIVERED"]

        if not (is_paid and is_completed):
            return


        try:

            if not shop_name:
                if hasattr(order, "shop") and order.shop and getattr(order.shop, "name", None):
                    shop_name = order.shop.name
                else:
                    shop_res = await self.db.execute(select(Shop.name).where(Shop.id == order.shop_id))
                    shop_name = shop_res.scalar_one_or_none()
            
            shop_name = shop_name or "Restaurant"
            raw_phone = order.customer_phone
            clean_phone = "".join(filter(str.isdigit, raw_phone))
            if not clean_phone:
                return
            if len(clean_phone) == 10:
                clean_phone = f"91{clean_phone}"

            amt_val = float(order.total_amount or 0.0)
            formatted_amount = f"₹{int(amt_val)}" if amt_val.is_integer() else f"₹{amt_val:.2f}"
            bill_id = order.id.hex[:8].upper()
            customer_name = order.customer_name or "Customer"
            customer_url = "https://menukit.debuggerstechnologies.com/customer/"

            def _send_wa():
                try:
                    from app.services.whatsapp_service import WhatsAppClient
                    wa = WhatsAppClient()
                    wa.send_order_create_template(
                        phone_number=clean_phone,
                        customer_name=customer_name,
                        shop_name=shop_name,
                        bill_id=bill_id,
                        amount_paid=formatted_amount,
                        customer_url=customer_url,
                    )
                except Exception as ex:
                    print(f"Failed to send order status WhatsApp to {clean_phone}: {ex}")

            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.run_in_executor(None, _send_wa)
            except RuntimeError:
                _send_wa()
        except Exception as e:
            print(f"Error initiating WhatsApp order status notification: {e}")

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

    async def append_items_to_order(self, order_id: uuid.UUID, shop_id: uuid.UUID, new_items: List[dict]) -> Order:
        """Append new order items to an existing active order and update total amount."""
        result = await self.db.execute(
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.id == order_id, Order.shop_id == shop_id)
        )
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        if order.order_status in ["completed", "cancelled"]:
            raise HTTPException(status_code=400, detail="Cannot add items to a completed or cancelled order")

        added_amount = 0.0
        for it in new_items:
            item_price = float(it.get("price", 0.0))
            quantity = int(it.get("quantity", 1))
            added_amount += item_price * quantity

            item = OrderItem(
                id=uuid.uuid4(),
                order_id=order.id,
                menu_item_id=uuid.UUID(str(it["menu_item_id"])) if isinstance(it["menu_item_id"], str) else it["menu_item_id"],
                name=it["name"],
                quantity=quantity,
                price=item_price,
                variant_info=it.get("variant_info"),
                addons_info=it.get("addons_info"),
            )
            self.db.add(item)

        order.total_amount = float(order.total_amount or 0.0) + added_amount
        await self.db.flush()
        return order

    async def toggle_order_item_completion(self, order_id: uuid.UUID, item_id: uuid.UUID, shop_id: uuid.UUID, is_completed: Optional[bool] = None) -> Order:
        """Toggle or set an order item's completion status."""
        result = await self.db.execute(
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.id == order_id, Order.shop_id == shop_id)
        )
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        item = next((it for it in order.items if it.id == item_id), None)
        if not item:
            raise HTTPException(status_code=404, detail="Order item not found")

        if is_completed is not None:
            item.is_completed = is_completed
        else:
            item.is_completed = not bool(item.is_completed)

        # If marked completed, un-cancel
        if item.is_completed:
            item.is_cancelled = False
            item.cancellation_reason = None

        await self.db.flush()
        return order

    async def toggle_order_item_cancel(
        self, order_id: uuid.UUID, item_id: uuid.UUID, shop_id: uuid.UUID, reason: Optional[str] = None
    ) -> Order:
        """Cancel or restore an individual order item and recalculate total amount."""
        result = await self.db.execute(
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.id == order_id, Order.shop_id == shop_id)
        )
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        item = next((it for it in order.items if it.id == item_id), None)
        if not item:
            raise HTTPException(status_code=404, detail="Order item not found")

        item_amount = float(item.price or 0.0) * int(item.quantity or 1)

        # Toggle cancellation
        item.is_cancelled = not bool(item.is_cancelled)
        if item.is_cancelled:
            item.is_completed = False
            item.cancellation_reason = reason or "Cancelled by staff"
            # Deduct from order total
            order.total_amount = max(0.0, float(order.total_amount or 0.0) - item_amount)
        else:
            item.cancellation_reason = None
            # Restore to order total
            order.total_amount = float(order.total_amount or 0.0) + item_amount

        # Automatic Order Status Transition:
        # If all items in the order are now cancelled, automatically mark the whole order as CANCELLED.
        active_items = [it for it in (order.items or []) if not it.is_cancelled]
        if not active_items and len(order.items or []) > 0:
            order.order_status = "CANCELLED"
            order.cancellation_reason = reason or "All items cancelled"
        elif active_items and order.order_status in ["CANCELLED", "cancelled"]:
            # If an item was restored and order was previously marked CANCELLED, revert back to active state
            order.order_status = "PREPARING" if order.order_type == "dine_in" else "ACCEPTED"
            order.cancellation_reason = None

        order.version = (order.version or 1) + 1
        await self.db.flush()
        return order

    async def replace_order_item(
        self,
        order_id: uuid.UUID,
        item_id: uuid.UUID,
        shop_id: uuid.UUID,
        replace_data: Any,
    ) -> Order:
        """Atomically cancel an order item with replacement note and append replacement item."""
        result = await self.db.execute(
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.id == order_id, Order.shop_id == shop_id)
        )
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        if order.order_status in ["completed", "cancelled"]:
            raise HTTPException(status_code=400, detail="Cannot modify items of a completed or cancelled order")

        old_item = next((it for it in order.items if it.id == item_id), None)
        if not old_item:
            raise HTTPException(status_code=404, detail="Original order item not found")

        # 1. Mark old item as cancelled with replacement note
        old_amount = float(old_item.price or 0.0) * int(old_item.quantity or 1)
        old_item.is_cancelled = True
        old_item.is_completed = False
        replace_reason = replace_data.reason or "Item replacement"
        old_item.cancellation_reason = f"Replaced with {replace_data.name} ({replace_reason})"

        # 2. Add new replacement item
        new_quantity = int(replace_data.quantity or 1)
        new_price = float(replace_data.price or 0.0)
        new_amount = new_price * new_quantity

        new_menu_item_id = (
            uuid.UUID(str(replace_data.new_menu_item_id))
            if isinstance(replace_data.new_menu_item_id, str)
            else replace_data.new_menu_item_id
        )

        replacement_item = OrderItem(
            id=uuid.uuid4(),
            order_id=order.id,
            menu_item_id=new_menu_item_id,
            name=replace_data.name,
            quantity=new_quantity,
            price=new_price,
            variant_info=replace_data.variant_info,
            addons_info=replace_data.addons_info,
            is_completed=False,
            is_cancelled=False,
            cancellation_reason=None,
        )
        self.db.add(replacement_item)

        # 3. Recalculate order total amount
        order.total_amount = max(0.0, float(order.total_amount or 0.0) - old_amount + new_amount)
        order.version = (order.version or 1) + 1

        await self.db.flush()
        return order



