"""Order management service."""

import uuid
import httpx
import asyncio
from fastapi import HTTPException
from sqlalchemy import select, func, or_, and_, cast, String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.order import Order, OrderItem
from app.models.shop import Shop
from app.models.shop_settings import ShopSettings
from app.schemas.order import OrderCreate
from app.core.config import get_settings
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


def format_time_12h(t_str: Optional[str]) -> str:
    """Format 24h HH:MM to 12h hh:mm AM/PM."""
    if not t_str:
        return ""
    clean = t_str.strip().upper()
    if "AM" in clean or "PM" in clean:
        return clean
    parts = clean.split(":")
    if len(parts) < 2:
        return clean
    try:
        h = int(parts[0])
        m = int(parts[1])
        period = "PM" if h >= 12 else "AM"
        display_h = 12 if (h % 12 == 0) else (h % 12)
        return f"{display_h:02d}:{m:02d} {period}"
    except Exception:
        return clean


def check_shop_operating_status(shop: Shop) -> tuple[bool, str]:
    """Check if the shop is currently active and within operating hours."""
    if not shop.is_active:
        return False, f"'{shop.name}' is currently inactive and not accepting orders."

    if not shop.opening_time or not shop.closing_time:
        return True, ""

    try:
        from datetime import datetime
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("Asia/Kolkata")
            now = datetime.now(tz)
        except Exception:
            now = datetime.now()

        def parse_minutes(t_str: str) -> Optional[int]:
            clean = t_str.strip().upper()
            is_pm = "PM" in clean
            is_am = "AM" in clean
            nums = "".join(c for c in clean if c.isdigit() or c == ':')
            parts = [int(p) for p in nums.split(':') if p]
            if len(parts) < 2:
                return None
            h, m = parts[0], parts[1]
            if is_pm and h < 12:
                h += 12
            if is_am and h == 12:
                h = 0
            return h * 60 + m

        open_min = parse_minutes(shop.opening_time)
        close_min = parse_minutes(shop.closing_time)

        if open_min is None or close_min is None or open_min == close_min:
            return True, ""

        current_min = now.hour * 60 + now.minute

        if close_min > open_min:
            is_open = open_min <= current_min < close_min
        else:
            if close_min == 0:
                is_open = current_min >= open_min
            else:
                is_open = current_min >= open_min or current_min < close_min

        if not is_open:
            current_time_str = now.strftime("%I:%M %p")
            open_formatted = format_time_12h(shop.opening_time)
            close_formatted = format_time_12h(shop.closing_time)
            return (
                False,
                f"'{shop.name}' is currently closed for orders. Operating hours: {open_formatted} to {close_formatted} (Current store time: {current_time_str})."
            )
        return True, ""
    except Exception:
        return True, ""


class OrderService:
    """Handles ordering logic and Cashfree Payment Gateway integration."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _broadcast_order_live(
        self,
        order: Order,
        event_type: str = "order_update",
        title: Optional[str] = None,
        message: Optional[str] = None,
    ):
        """Instantaneously broadcasts order updates with 0 delay to merchant dashboard and customer live sockets."""
        try:
            from app.services.websocket_manager import manager, customer_manager

            order_ref = f"#{order.daily_order_number}" if order.daily_order_number else f"#{order.id.hex[:8]}"
            default_title = f"Order {order_ref} Update"
            default_msg = f"Order {order_ref} status is {order.order_status}."

            clean_phone = "".join(filter(str.isdigit, order.customer_phone or ""))
            if len(clean_phone) > 10:
                clean_phone = clean_phone[-10:]
            customer_ws_id = get_customer_user_id(clean_phone) if clean_phone else str(order.id)

            # Build structured order payload
            order_payload = {
                "id": str(order.id),
                "shop_id": str(order.shop_id),
                "daily_order_number": order.daily_order_number,
                "customer_name": order.customer_name,
                "customer_phone": order.customer_phone,
                "order_type": order.order_type,
                "table_number": order.table_number,
                "delivery_address": order.delivery_address,
                "order_status": order.order_status,
                "payment_status": order.payment_status,
                "payment_method": order.payment_method,
                "total_amount": float(order.total_amount or 0.0),
                "payment_expires_at": order.payment_expires_at.isoformat() if getattr(order, "payment_expires_at", None) else None,
                "created_at": order.created_at.isoformat() if hasattr(order, "created_at") and order.created_at else None,
                "items": [
                    {
                        "id": str(it.id),
                        "name": it.name,
                        "quantity": it.quantity,
                        "price": float(it.price or 0.0),
                        "variant_info": it.variant_info,
                        "addons_info": it.addons_info,
                        "is_completed": bool(getattr(it, "is_completed", False)),
                        "is_cancelled": bool(getattr(it, "is_cancelled", False)),
                        "cancellation_reason": getattr(it, "cancellation_reason", None)
                    } for it in (order.items or [])
                ]
            }

            # 1. Shop Broadcast (Merchant Dashboard)
            shop_msg = {
                "event": event_type,
                "type": event_type,
                "data": order_payload,
                "order": order_payload,
                "order_id": str(order.id),
                "status": order.order_status,
                "payment_status": order.payment_status,
                "title": title or default_title,
                "message": message or default_msg
            }
            await manager.broadcast_to_shop(str(order.shop_id), shop_msg)

            # 2. Customer Broadcast (Live Tracker / Active orders floating bar)
            cust_msg = {
                "type": "order_update",
                "event": "order_update",
                "order_id": str(order.id),
                "daily_order_number": order.daily_order_number,
                "status": order.order_status,
                "payment_status": order.payment_status,
                "customer_phone": order.customer_phone,
                "order_type": order.order_type,
                "table_number": order.table_number,
                "total_amount": float(order.total_amount or 0.0),
                "payment_expires_at": order.payment_expires_at.isoformat() if getattr(order, "payment_expires_at", None) else None,
                "data": order_payload,
                "order": order_payload
            }

            # Concurrently broadcast to all customer identifier targets for 0 delay
            targets = {str(order.id), customer_ws_id}
            if clean_phone:
                targets.add(clean_phone)
            if order.customer_phone:
                targets.add(order.customer_phone)

            await asyncio.gather(*[
                customer_manager.broadcast_to_customer(target, cust_msg)
                for target in targets
            ], return_exceptions=True)
        except Exception as e:
            print(f"Error in _broadcast_order_live: {e}")

    async def create_order(self, shop_id: uuid.UUID, data: OrderCreate) -> Order:
        """Create a new customer order and initialize payment session if online."""
        # 1. Fetch shop and settings
        result = await self.db.execute(select(Shop).where(Shop.id == shop_id))
        shop = result.scalar_one_or_none()
        if not shop:
            raise HTTPException(status_code=404, detail="Restaurant not found")

        # 1b. Check if restaurant is active and open for business
        is_open, closed_msg = check_shop_operating_status(shop)
        if not is_open:
            raise HTTPException(status_code=400, detail=closed_msg or "Restaurant is currently closed for orders.")

        settings_result = await self.db.execute(select(ShopSettings).where(ShopSettings.shop_id == shop.id))
        settings = settings_result.scalar_one_or_none()
        if not settings:
            raise HTTPException(status_code=400, detail="Ordering is not configured for this restaurant")

        # 2. Check channel availability & bank verification
        is_bank_verified = bool(settings.bank_account_last4) and settings.razorpay_route_status in ["activated", "active"]
        if not is_bank_verified:
            raise HTTPException(status_code=400, detail="Ordering is temporarily unavailable as restaurant settlement account verification is pending.")

        if data.order_type == "delivery":
            if not settings.delivery_enabled:
                raise HTTPException(status_code=400, detail="Delivery option is not available")
            
            # Check maximum coverable delivery distance
            max_dist = float(getattr(settings, "max_delivery_distance", 0.0) or 0.0)
            if max_dist > 0 and shop.latitude and shop.longitude and data.delivery_address:
                import re
                import math
                loc_match = re.search(r"\[loc=(-?\d+\.?\d*),(-?\d+\.?\d*)\]", data.delivery_address)
                if loc_match:
                    try:
                        cust_lat = float(loc_match.group(1))
                        cust_lng = float(loc_match.group(2))
                        
                        # Haversine distance formula
                        r = 6371.0  # Earth radius in km
                        dlat = math.radians(cust_lat - float(shop.latitude))
                        dlon = math.radians(cust_lng - float(shop.longitude))
                        a = math.sin(dlat / 2.0) ** 2 + math.cos(math.radians(float(shop.latitude))) * math.cos(math.radians(cust_lat)) * math.sin(dlon / 2.0) ** 2
                        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
                        dist_km = r * c
                        
                        if dist_km > max_dist:
                            raise HTTPException(
                                status_code=400,
                                detail=f"Delivery is out of range. The restaurant only delivers within {max_dist:.1f} km (your location is {dist_km:.1f} km away)."
                            )
                    except (ValueError, TypeError):
                        pass
        if data.order_type == "takeaway" and not settings.takeaway_enabled:
            raise HTTPException(status_code=400, detail="Takeaway option is not available")
        if data.order_type == "dine_in" and not settings.dinein_enabled:
            raise HTTPException(status_code=400, detail="Dine-in option is not available")

        from datetime import datetime, timezone
        import pytz
        ist_tz = pytz.timezone('Asia/Kolkata')
        now_ist = datetime.now(ist_tz)
        today_start_ist = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_utc = today_start_ist.astimezone(timezone.utc)

        clean_req_phone = "".join(filter(str.isdigit, data.customer_phone or ""))
        if clean_req_phone:
            phone_10 = clean_req_phone[-10:]
            phone_variants = [phone_10, f"+91{phone_10}", f"91{phone_10}", f"0{phone_10}"]

            # Cross-Channel Rule 1: If placing Dine-In, block if customer has an active Takeaway or Delivery order from today
            if data.order_type == "dine_in":
                active_td_stmt = (
                    select(Order)
                    .where(
                        Order.shop_id == shop.id,
                        Order.customer_phone.in_(phone_variants),
                        Order.created_at >= today_start_utc,
                        func.lower(Order.order_type).in_(["takeaway", "delivery"]),
                        func.lower(Order.order_status).notin_(["completed", "cancelled", "rejected", "delivered"])
                    )
                    .order_by(Order.created_at.desc())
                )
                active_td_res = await self.db.execute(active_td_stmt)
                active_td_order = active_td_res.scalars().first()
                if active_td_order:
                    order_ref = f"#{active_td_order.daily_order_number}" if active_td_order.daily_order_number else f"#{active_td_order.id.hex[:8]}"
                    channel_title = "Takeaway" if str(active_td_order.order_type).lower() == "takeaway" else "Delivery"
                    raise HTTPException(
                        status_code=400,
                        detail=f"You have an ongoing {channel_title} order ({order_ref}) at this restaurant. Please complete or receive that order before placing a Dine-in order."
                    )

            # Cross-Channel Rule 2: If placing Takeaway or Delivery, block only if customer has an UNSETTLED / UNPAID active Dine-in order from today
            elif data.order_type in ["takeaway", "delivery"]:
                active_di_stmt = (
                    select(Order)
                    .where(
                        Order.shop_id == shop.id,
                        Order.customer_phone.in_(phone_variants),
                        Order.created_at >= today_start_utc,
                        func.lower(Order.order_type) == "dine_in",
                        func.lower(Order.order_status).notin_(["completed", "cancelled", "rejected", "delivered", "paid"]),
                        func.lower(Order.payment_status) != "paid"
                    )
                    .order_by(Order.created_at.desc())
                )
                active_di_res = await self.db.execute(active_di_stmt)
                active_di_order = active_di_res.scalars().first()
                if active_di_order:
                    order_ref = f"#{active_di_order.daily_order_number}" if active_di_order.daily_order_number else f"#{active_di_order.id.hex[:8]}"
                    tbl_label = f" on Table #{active_di_order.table_number}" if active_di_order.table_number else ""
                    channel_title = "Takeaway" if data.order_type == "takeaway" else "Delivery"
                    raise HTTPException(
                        status_code=400,
                        detail=f"You currently have an active Dine-in order ({order_ref}){tbl_label}. Please complete and settle your dine-in bill before placing a {channel_title} order."
                    )

                # Cross-Channel Rule 3: If placing Takeaway or Delivery, block if previous Takeaway/Delivery order from today is not (Accepted AND Paid)
                active_order_stmt = (
                    select(Order)
                    .where(
                        Order.shop_id == shop.id,
                        Order.customer_phone.in_(phone_variants),
                        Order.created_at >= today_start_utc,
                        func.lower(Order.order_type).in_(["takeaway", "delivery"]),
                        func.lower(Order.order_status).notin_(["completed", "cancelled", "rejected", "delivered"])
                    )
                    .order_by(Order.created_at.desc())
                )
                active_order_res = await self.db.execute(active_order_stmt)
                active_order = active_order_res.scalars().first()
                if active_order:
                    norm_status = str(active_order.order_status or "").upper()
                    is_accepted = norm_status not in ["PENDING_VENDOR", "PENDING"]
                    is_paid = str(active_order.payment_status or "").lower() == "paid"
                    
                    if not (is_accepted and is_paid):
                        order_ref = f"#{active_order.daily_order_number}" if active_order.daily_order_number else f"#{active_order.id.hex[:8]}"
                        channel_title = "Takeaway" if str(active_order.order_type).lower() == "takeaway" else "Delivery"
                        if not is_accepted:
                            raise HTTPException(
                                status_code=400,
                                detail=f"You already have an active {channel_title} order ({order_ref}) waiting for restaurant acceptance. Please wait for acceptance and complete payment before placing another order."
                            )
                        else:
                            raise HTTPException(
                                status_code=400,
                                detail=f"You have an accepted {channel_title} order ({order_ref}) awaiting payment. Please complete payment for that order before placing a new order."
                            )

        # 3. Determine status
        if settings.auto_accept_orders:
            # For dine-in or cash orders with auto-accept, set directly to ACCEPTED (paid on delivery/counter/at last)
            if data.order_type == "dine_in" or data.payment_method in ["cash", "cash_on_delivery", "counter"]:
                initial_status = "ACCEPTED"
            else:
                initial_status = "PAYMENT_PENDING"
        else:
            # Standard initial status requires vendor acceptance
            initial_status = "PENDING_VENDOR"

        # Dine-In Table Merging & Occupation Verification
        if data.order_type == "dine_in" and data.table_number and str(data.table_number).strip():
            tbl_val = str(data.table_number).strip()
            tbl_num_only = "".join(filter(str.isdigit, tbl_val))
            tbl_variants = [tbl_val, tbl_val.lower(), tbl_val.upper()]
            if tbl_num_only:
                tbl_variants.extend([tbl_num_only, f"Table-{tbl_num_only}", f"Table {tbl_num_only}", f"TABLE-{tbl_num_only}", f"table-{tbl_num_only}"])

            from sqlalchemy.orm import selectinload
            active_tbl_stmt = (
                select(Order)
                .options(selectinload(Order.items))
                .where(
                    Order.shop_id == shop.id,
                    Order.created_at >= today_start_utc,
                    func.lower(Order.order_type) == "dine_in",
                    func.lower(Order.table_number).in_([v.lower() for v in tbl_variants]),
                    func.lower(Order.order_status).notin_(["completed", "cancelled", "rejected", "delivered"])
                )
            )
            active_tbl_res = await self.db.execute(active_tbl_stmt)
            existing_dinein_order = active_tbl_res.scalars().first()

            if existing_dinein_order:
                clean_req_phone = "".join(filter(str.isdigit, data.customer_phone or ""))
                clean_ord_phone = "".join(filter(str.isdigit, existing_dinein_order.customer_phone or ""))

                is_same_customer = False
                if clean_req_phone and clean_ord_phone and clean_req_phone[-10:] == clean_ord_phone[-10:]:
                    is_same_customer = True
                elif not clean_ord_phone and not clean_req_phone:
                    is_same_customer = True

                if is_same_customer:
                    # Require admin acceptance before adding more items
                    norm_status = str(existing_dinein_order.order_status or "").upper()
                    if norm_status in ["PENDING_VENDOR", "PENDING"]:
                        order_ref = f"#{existing_dinein_order.daily_order_number}" if existing_dinein_order.daily_order_number else f"#{existing_dinein_order.id.hex[:8]}"
                        raise HTTPException(
                            status_code=400,
                            detail=f"Your initial table order ({order_ref}) is awaiting restaurant acceptance. You can add more items once accepted by the restaurant."
                        )

                if is_same_customer:
                    # Validate all menu items exist
                    from app.models.menu_item import MenuItem
                    menu_item_ids = [it.menu_item_id for it in data.items]
                    from app.models.category import Category
                    val_res = await self.db.execute(
                        select(MenuItem).join(Category).where(
                            MenuItem.id.in_(menu_item_ids),
                            MenuItem.is_available == True,
                            Category.is_active == True
                        )
                    )
                    existing_items = val_res.scalars().all()
                    existing_ids = {item.id for item in existing_items}

                    for it in data.items:
                        if it.menu_item_id not in existing_ids:
                            raise HTTPException(
                                status_code=400,
                                detail=f"Item '{it.name}' is no longer available. Please remove it from your cart and try again."
                            )

                    # Append new items to existing active dine-in order
                    for it in data.items:
                        new_item = OrderItem(
                            id=uuid.uuid4(),
                            order_id=existing_dinein_order.id,
                            menu_item_id=it.menu_item_id,
                            name=it.name,
                            quantity=it.quantity,
                            price=it.price,
                            variant_info=it.variant_info,
                            addons_info=it.addons_info,
                            is_completed=False,
                            is_cancelled=False,
                            cancellation_reason=None
                        )
                        self.db.add(new_item)

                    await self.db.flush()
                    await self.db.refresh(existing_dinein_order, attribute_names=["items"])

                    # Recompute total_amount with GST
                    active_subtotal = sum(
                        float(item.price or 0.0) * int(item.quantity or 1)
                        for item in (existing_dinein_order.items or [])
                        if not item.is_cancelled
                    )
                    tax_amount = 0.0
                    if settings.gst_enabled and not settings.inclusive_tax:
                        cgst_rate = float(settings.cgst_rate or 0.0)
                        sgst_rate = float(settings.sgst_rate or 0.0)
                        total_tax_rate = cgst_rate + sgst_rate
                        tax_amount = round(active_subtotal * (total_tax_rate / 100.0), 2)

                    existing_dinein_order.total_amount = round(active_subtotal + tax_amount, 2)
                    existing_dinein_order.version = (existing_dinein_order.version or 1) + 1

                    # Create persistent notification for merchant for added items
                    from app.services.notification_service import NotificationService
                    notif_service = NotificationService(self.db)
                    await notif_service.create_notification(
                        shop_id=shop.id,
                        type="ORDER_UPDATED",
                        title=f"New Items Added — {existing_dinein_order.table_number}",
                        message=f"{len(data.items)} new items added to active Order #{existing_dinein_order.daily_order_number or existing_dinein_order.id.hex[:8]} by {existing_dinein_order.customer_name}",
                        metadata={"order_id": str(existing_dinein_order.id)}
                    )

                    # Broadcast live update
                    await self._broadcast_order_live(
                        order=existing_dinein_order,
                        event_type="ITEMS_ADDED",
                        title=f"Items Added to {existing_dinein_order.table_number}",
                        message=f"{len(data.items)} items added to Order #{existing_dinein_order.daily_order_number}"
                    )

                    await self.db.flush()
                    return existing_dinein_order
                else:
                    # Occupied by another customer
                    raise HTTPException(
                        status_code=400,
                        detail=f"{data.table_number} is currently occupied. Please select a different table or contact staff."
                    )

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

        # Calculate daily order number (Reset at midnight IST)
        from datetime import datetime, timezone
        import pytz
        ist_tz = pytz.timezone('Asia/Kolkata')
        now_ist = datetime.now(ist_tz)
        today_start_ist = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_utc = today_start_ist.astimezone(timezone.utc)
        
        max_order_result = await self.db.execute(
            select(func.max(Order.daily_order_number))
            .where(Order.shop_id == shop.id)
            .where(Order.created_at >= today_start_utc)
        )
        max_daily_num = max_order_result.scalar() or 0
        new_daily_num = max_daily_num + 1

        order = Order(
            id=order_id,
            shop_id=shop.id,
            daily_order_number=new_daily_num,
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

        # Validate and record discount usages
        applied_ids = getattr(data, "applied_discount_ids", None) or []
        applied_codes = getattr(data, "applied_discount_codes", None) or []
        if applied_ids or applied_codes:
            await self._record_discount_usages(order, applied_ids, applied_codes)

        # Create persistent notification for merchant (for non-online payment methods or dine-in orders)
        if data.payment_method != "online" or data.order_type == "dine_in":
            from app.services.notification_service import NotificationService
            notif_service = NotificationService(self.db)
            await notif_service.create_notification(
                shop_id=shop.id,
                type="NEW_ORDER",
                title="New Order Received",
                message=f"New order #{order.id.hex[:8]} placed by {order.customer_name} ({order.order_type})",
                metadata={"order_id": str(order.id)}
            )

        # 0-delay Instant WebSocket broadcast to Merchant & Customer
        await self._broadcast_order_live(
            order=order,
            event_type="NEW_ORDER",
            title="New Order Received",
            message=f"New order #{order.id.hex[:8]} placed by {order.customer_name} ({order.order_type})"
        )

        await self.db.flush()
        
        # Automatically award 0.15 contest credits if order total >= ₹100 for non-online orders
        if data.payment_method != "online" and float(order.total_amount) >= 100.0:
            await self._award_contest_credits_if_eligible(order)

        # Send WhatsApp payment required notification if order starts in PAYMENT_PENDING (e.g. auto-accept enabled)
        if initial_status == "PAYMENT_PENDING" and initial_pay_status != "paid" and data.payment_method not in ["cash", "cash_on_delivery", "counter"]:
            await self._send_order_accepted_payment_required_whatsapp_notification(order, shop_name=shop.name)

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
                "return_url": f"https://menukit.debuggerstechnologies.com/shop/{order.shop_id}/order/{order.id}?payment_success=true&link_id={link_id}"
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
                            if order.order_status.upper() in ["PAYMENT_PENDING", "PENDING_VENDOR", "PENDING"]:
                                order.order_status = "PAID"
                        elif cf_status in ["CANCELLED", "EXPIRED"]:
                            order.payment_status = "failed"
                    else:
                        cf_status = res_data.get("order_status")
                        if cf_status == "PAID":
                            order.payment_status = "paid"
                            if order.order_status.upper() in ["PAYMENT_PENDING", "PENDING_VENDOR", "PENDING"]:
                                order.order_status = "PAID"
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

        # Auto-repair zero/null total_amount when order has active items
        if (order.total_amount is None or float(order.total_amount) <= 0.0) and order.items:
            active_items = [it for it in order.items if not it.is_cancelled]
            if active_items:
                active_subtotal = sum(float(it.price or 0.0) * int(it.quantity or 1) for it in active_items)
                settings_stmt = select(ShopSettings).where(ShopSettings.shop_id == order.shop_id)
                settings_res = await self.db.execute(settings_stmt)
                shop_st = settings_res.scalar_one_or_none()
                tax_amount = 0.0
                if shop_st and shop_st.gst_enabled and not shop_st.inclusive_tax:
                    cgst_rate = float(shop_st.cgst_rate or 0.0)
                    sgst_rate = float(shop_st.sgst_rate or 0.0)
                    total_tax_rate = cgst_rate + sgst_rate
                    tax_amount = round(active_subtotal * (total_tax_rate / 100.0), 2)
                order.total_amount = round(active_subtotal + tax_amount, 2)
                await self.db.flush()

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
                # All orders waiting for customer payment
                conditions.append(Order.order_status.in_(["PAYMENT_PENDING"]))
            elif status_filter in ["preparing", "awaiting_complete", "accepted"]:
                # Awaiting complete includes paid/accepted orders being prepared or served
                conditions.append(Order.order_status.in_(["PAID", "accepted", "ACCEPTED", "PREPARING", "READY"]))
            elif status_filter == "completed":
                conditions.append(Order.order_status.in_(["DELIVERED", "COMPLETED", "completed"]))
            elif status_filter == "cancelled":
                conditions.append(Order.order_status.in_(["CANCELLED", "OUT_FOR_DELIVERY", "rejected", "cancelled"]))
            elif status_filter in ["awaiting_refund", "refund_pending", "refund_failed"]:
                conditions.append(
                    or_(
                        Order.payment_status.in_(["refund_pending", "refund_failed", "awaiting_refund"]),
                        and_(
                            Order.order_status.in_(["CANCELLED", "rejected", "cancelled"]),
                            Order.payment_status.in_(["paid", "partially_refunded"])
                        )
                    )
                )

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
            select(Order.order_status, Order.order_type, Order.payment_status, func.count(Order.id))
            .where(*conditions)
            .group_by(Order.order_status, Order.order_type, Order.payment_status)
        )
        result = await self.db.execute(stmt)
        rows = result.all()

        new_count = 0
        awaiting_payment_count = 0
        awaiting_complete_count = 0
        completed_count = 0
        cancelled_count = 0
        awaiting_refund_count = 0
        all_count = 0

        for status_val, order_type_val, pay_status_val, count_val in rows:
            all_count += count_val
            s = (status_val or "").upper()
            t = (order_type_val or "").lower()
            p = (pay_status_val or "").lower()

            if s in ["PENDING_VENDOR", "PENDING"]:
                new_count += count_val
            elif s == "PAYMENT_PENDING":
                awaiting_payment_count += count_val
            elif s in ["PAID", "ACCEPTED", "PREPARING", "READY"]:
                awaiting_complete_count += count_val
            elif s in ["DELIVERED", "COMPLETED"]:
                completed_count += count_val
            elif s in ["CANCELLED", "OUT_FOR_DELIVERY", "REJECTED"]:
                cancelled_count += count_val

            if p in ["refund_pending", "refund_failed", "awaiting_refund"] or (s in ["CANCELLED", "REJECTED"] and p in ["paid", "partially_refunded"]):
                awaiting_refund_count += count_val

        return {
            "all": all_count,
            "new": new_count,
            "awaiting_payment": awaiting_payment_count,
            "accepted": awaiting_complete_count,
            "preparing": awaiting_complete_count,
            "awaiting_complete": awaiting_complete_count,
            "completed": completed_count,
            "cancelled": cancelled_count,
            "awaiting_refund": awaiting_refund_count,
        }




    async def get_orders_by_user(self, user_id: uuid.UUID) -> list[Order]:
        """Fetch all orders for a merchant's shop based on user ID."""
        # Find shop first
        result = await self.db.execute(select(Shop).where(Shop.user_id == user_id))
        shop = result.scalar_one_or_none()
        if not shop:
            raise HTTPException(status_code=404, detail="Shop not found")
        return await self.get_shop_orders(shop.id)

    @staticmethod
    def _resolve_razorpay_payment_id(rzp_client, rzp_id: str) -> str:
        """Resolve a valid 'pay_...' ID from an order or payment reference."""
        if not rzp_id:
            return ""
        if str(rzp_id).startswith("pay_"):
            return str(rzp_id)
        if str(rzp_id).startswith("order_"):
            try:
                resp = rzp_client.order.payments(str(rzp_id))
                items = resp.get("items", []) if isinstance(resp, dict) else []
                for p in items:
                    if p.get("status") in ["captured", "authorized"]:
                        return p.get("id")
                if items:
                    return items[0].get("id")
            except Exception as e:
                print(f"Failed to fetch payments for razorpay order {rzp_id}: {e}")
        return str(rzp_id)

    async def update_payment_status(self, order_id: uuid.UUID, payment_status: str, shop_id: uuid.UUID) -> Order:
        """Update the payment status of an order (merchant only). If 'refunded' and paid online, triggers Razorpay refund."""
        from app.models.shop_settings import ShopSettings
        import httpx
        
        # Verify order belongs to shop
        order = await self.get_order_by_id(order_id)
        if order.shop_id != shop_id:
            raise HTTPException(status_code=403, detail="Not authorized")

        norm_order_status = str(order.order_status or "").upper()
        if norm_order_status in ["COMPLETED", "DELIVERED"]:
            raise HTTPException(status_code=400, detail="Cannot change payment status of an order that is already completed.")
        if norm_order_status in ["CANCELLED", "REJECTED"] and payment_status != "refunded":
            raise HTTPException(status_code=400, detail="Cannot change payment status of an order that is already cancelled.")

        # Auto-refund via Razorpay if marking as refunded and payment was online
        if payment_status == "refunded":
            if str(order.payment_status or "").lower() not in ["paid", "partially_refunded", "refund_pending", "refund_failed"]:
                raise HTTPException(status_code=400, detail="Cannot refund an order that has not been paid.")
            if str(order.payment_method or "").lower() != "online":
                raise HTTPException(status_code=400, detail="Automatic refund is only available for orders paid online via payment gateway.")
            if not (order.cashfree_order_id or order.payment_session_id or order.razorpay_order_id):
                raise HTTPException(status_code=400, detail="No online payment gateway transaction found for this order.")

            # Razorpay refund — uses the captured payment_session_id (= razorpay_payment_id)
            rzp_payment_id = order.payment_session_id or order.razorpay_order_id
            order_ref = f"#{order.daily_order_number or order.id.hex[:8]}"
            print(f"\033[96m\033[1m💸 [RAZORPAY REFUND INITIATED] Order {order_ref} ➔ Amount: ₹{float(order.total_amount):.2f} | Payment ID: {rzp_payment_id}\033[0m")
            if rzp_payment_id:
                from app.core.config import get_settings as _get_settings
                _cfg = _get_settings()
                try:
                    if not _cfg.MOCK_PAYMENT_MODE and not str(rzp_payment_id).startswith("pay_mock_") and not str(rzp_payment_id).startswith("order_mock_"):
                        import razorpay as _rzp
                        rzp_client = _rzp.Client(auth=(_cfg.RAZORPAY_KEY_ID, _cfg.RAZORPAY_KEY_SECRET))
                        actual_pay_id = self._resolve_razorpay_payment_id(rzp_client, rzp_payment_id)
                        refund_res = rzp_client.payment.refund(actual_pay_id, {
                            "amount": int(round(float(order.total_amount) * 100)),  # paise
                            "reverse_all": 1,
                            "notes": {
                                "order_id": str(order.id),
                                "reason": "Order refunded by merchant"
                            }
                        })
                        if refund_res and "id" in refund_res:
                            order.refund_id = refund_res["id"]
                    else:
                        order.refund_id = f"rfnd_mock_{uuid.uuid4().hex[:12]}"
                    print(f"\033[92m\033[1m✅ [RAZORPAY REFUND SUCCESS] Order {order_ref} ➔ ₹{float(order.total_amount):.2f} refunded successfully (Refund ID: {order.refund_id})\033[0m")

                    # Send WhatsApp refund notification to customer
                    if order.customer_phone:
                        try:
                            from app.services.whatsapp_service import WhatsAppClient
                            wa = WhatsAppClient()
                            shop_res = await self.db.execute(select(Shop.name).where(Shop.id == shop_id))
                            shop_name = shop_res.scalar_one_or_none() or "Restaurant"
                            order_num = str(order.daily_order_number or order.id.hex[:8]).upper()
                            await asyncio.to_thread(
                                wa.send_order_refund_template,
                                phone_number=order.customer_phone,
                                customer_name=order.customer_name or "Customer",
                                order_number=order_num,
                                shop_name=shop_name,
                                items_summary="Order refunded by restaurant",
                                refund_amount=f"{float(order.total_amount):.2f}",
                                order_id_tag=f"#{order_num}",
                                refund_method="Online",
                                timeline_days="5-7",
                                shop_id=str(shop_id),
                                order_id=str(order.id),
                            )
                        except Exception as wa_e:
                            print(f"\033[91m[WHATSAPP] Failed to send refund notification: {wa_e}\033[0m")
                except Exception as e:
                    print(f"\033[91m\033[1m❌ [RAZORPAY REFUND FAILED] Order {order_ref} ➔ {e}\033[0m")
                    order.payment_status = "refund_failed"
                    raise HTTPException(status_code=502, detail=f"Razorpay refund failed: {str(e)}")


        order.payment_status = payment_status
        
        # If manually marked as paid, advance the order status if pending, and notify WhatsApp
        if payment_status.lower() == "paid":
            if order.order_status == "PAYMENT_PENDING":
                order.order_status = "PAID"
                order.payment_expires_at = None

            await self._send_order_status_whatsapp_notification(order)

            # Broadcast to shop and create notification
            try:
                from app.services.notification_service import NotificationService
                from app.services.websocket_manager import manager
                from app.schemas.order import OrderResponse

                order_ref = f"#{order.daily_order_number}" if order.daily_order_number else f"#{order.id.hex[:8]}"
                notif_service = NotificationService(self.db)
                await notif_service.create_notification(
                    shop_id=shop_id,
                    type="NEW_ORDER",
                    title="Order Paid",
                    message=f"Order {order_ref} marked as paid.",
                    metadata={"order_id": str(order.id)}
                )
                ws_msg = {
                    "event": "NEW_ORDER",
                    "type": "NEW_ORDER",
                    "data": OrderResponse.model_validate(order).model_dump(mode="json"),
                    "title": "Order Paid",
                    "message": f"Order {order_ref} marked as paid."
                }
                await manager.broadcast_to_shop(str(shop_id), ws_msg)
            except Exception as e:
                print(f"Failed to broadcast shop paid event: {e}")
            
        return order

    async def retry_order_refund(self, order_id: uuid.UUID, shop_id: uuid.UUID) -> Order:
        """Retry processing Razorpay refund for a paid online order that is cancelled or failed refund."""
        order = await self.get_order_by_id(order_id)
        if order.shop_id != shop_id:
            raise HTTPException(status_code=403, detail="Not authorized")

        if str(order.payment_method or "").lower() != "online":
            raise HTTPException(status_code=400, detail="Only online payment orders can be refunded via Razorpay.")

        rzp_payment_id = order.payment_session_id or order.razorpay_order_id
        if not rzp_payment_id:
            raise HTTPException(status_code=400, detail="Missing payment gateway transaction ID for this order.")

        from app.core.config import get_settings as _get_settings
        _cfg = _get_settings()
        order_ref = f"#{order.daily_order_number or order.id.hex[:8]}"

        try:
            if not _cfg.MOCK_PAYMENT_MODE and not str(rzp_payment_id).startswith("pay_mock_") and not str(rzp_payment_id).startswith("order_mock_"):
                import razorpay as _rzp
                rzp_client = _rzp.Client(auth=(_cfg.RAZORPAY_KEY_ID, _cfg.RAZORPAY_KEY_SECRET))
                actual_pay_id = self._resolve_razorpay_payment_id(rzp_client, rzp_payment_id)
                amount_paise = int(round(float(order.total_amount) * 100))
                try:
                    pay_obj = rzp_client.payment.fetch(actual_pay_id)
                    captured_paise = int(pay_obj.get("amount", 0)) - int(pay_obj.get("amount_refunded", 0))
                    if captured_paise > 0 and amount_paise > captured_paise:
                        amount_paise = captured_paise
                except Exception as f_err:
                    print(f"Could not fetch payment balance from Razorpay in retry_order_refund: {f_err}")

                refund_data = {
                    "amount": amount_paise,
                    "reverse_all": 1,
                    "notes": {
                        "order_id": str(order.id),
                        "reason": order.cancellation_reason or "Manual refund initiated by merchant"
                    }
                }
                refund_res = rzp_client.payment.refund(actual_pay_id, refund_data)
                if refund_res and "id" in refund_res:
                    order.refund_id = refund_res["id"]
            else:
                order.refund_id = f"rfnd_mock_{uuid.uuid4().hex[:12]}"

            order.payment_status = "refunded"
            print(f"\033[92m\033[1m✅ [MANUAL REFUND SUCCESS] Order {order_ref} → ₹{float(order.total_amount):.2f} refunded (Payment ID: {rzp_payment_id}, Refund ID: {order.refund_id})\033[0m")

            if order.customer_phone:
                try:
                    from app.services.whatsapp_service import WhatsAppClient
                    wa = WhatsAppClient()
                    shop_res = await self.db.execute(select(Shop.name).where(Shop.id == shop_id))
                    shop_name = shop_res.scalar_one_or_none() or "Restaurant"
                    order_num = str(order.daily_order_number or order.id.hex[:8]).upper()
                    await asyncio.to_thread(
                        wa.send_order_refund_template,
                        phone_number=order.customer_phone,
                        customer_name=order.customer_name or "Customer",
                        order_number=order_num,
                        shop_name=shop_name,
                        items_summary="Order refunded by restaurant",
                        refund_amount=f"{float(order.total_amount):.2f}",
                        order_id_tag=f"#{order_num}",
                        refund_method="Online",
                        timeline_days="5-7",
                        shop_id=str(shop_id),
                        order_id=str(order.id),
                    )
                except Exception as wa_e:
                    print(f"\033[91m[WHATSAPP] Failed to send manual refund notification: {wa_e}\033[0m")

            await self.db.commit()
            await self.db.refresh(order)
            await self._broadcast_order_live(order, event_type="ORDER_UPDATED")
            return order

        except Exception as e:
            order.payment_status = "refund_failed"
            await self.db.commit()
            await self.db.refresh(order)
            print(f"\033[91m\033[1m❌ [MANUAL REFUND FAILED] Order {order_ref} → {e}\033[0m")
            raise HTTPException(status_code=502, detail=f"Razorpay refund failed: {str(e)}")

    async def update_order_status(self, order_id: uuid.UUID, status: str, shop_id: uuid.UUID, cancellation_reason: str = None, user_id: Optional[uuid.UUID] = None) -> Order:
        """Update the status of an order (merchant only)."""
        
        order = await self.get_order_by_id(order_id)
        if order.shop_id != shop_id:
            raise HTTPException(status_code=403, detail="Not authorized")

        current_status = str(order.order_status or "").upper()
        status = status.upper()

        if current_status in ["COMPLETED", "DELIVERED", "CANCELLED", "REJECTED"]:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot change status of an order that is already {current_status.capitalize()}."
            )

        if status in ["COMPLETED", "DELIVERED"]:
            if str(order.payment_status or "").lower() != "paid":
                raise HTTPException(
                    status_code=400,
                    detail="Order must be marked as Paid before it can be marked as Completed."
                )

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

        # Enforce that online orders must be paid before proceeding with preparation
        if status in ["PREPARING", "READY"] and order.payment_status.lower() != "paid" and order.payment_method.lower() not in ["cash", "cash_on_delivery", "counter"]:
            raise HTTPException(status_code=400, detail="Cannot proceed with order preparation until customer payment is confirmed.")

        # ──────────────────────────────────────────────────────────────────────
        # RACE CONDITION HANDLING: Admin cancels while customer is paying (Razorpay)
        # ──────────────────────────────────────────────────────────────────────
        if status == "CANCELLED":
            order_ref = f"#{order.daily_order_number or order.id.hex[:8]}"
            is_online = str(order.payment_method or "").lower() == "online"
            is_paid = str(order.payment_status or "").lower() in ["paid", "partially_refunded"]
            is_mid_payment = str(order.payment_status or "").lower() in ["not_paid", "awaiting_payment", "pending"]

            # Mark all items as cancelled so invoice and status views accurately show cancellation
            for it in (order.items or []):
                it.is_cancelled = True
                if not it.cancellation_reason:
                    it.cancellation_reason = cancellation_reason or "Order cancelled"

            # Case A: Customer already completed payment → auto-refund immediately via Razorpay
            # order.payment_session_id stores the captured razorpay_payment_id
            if is_online and is_paid and (order.payment_session_id or order.razorpay_order_id):
                from app.core.config import get_settings as _get_settings
                _cfg = _get_settings()
                rzp_payment_id = order.payment_session_id or order.razorpay_order_id
                print(f"\033[93m\033[1m⚠️  [ADMIN CANCEL + AUTO-REFUND] Order {order_ref} was already PAID. Triggering Razorpay refund of ₹{float(order.total_amount):.2f} on payment {rzp_payment_id}...\033[0m")
                try:
                    if not _cfg.MOCK_PAYMENT_MODE and not str(rzp_payment_id).startswith("pay_mock_") and not str(rzp_payment_id).startswith("order_mock_"):
                        import razorpay as _rzp
                        rzp_client = _rzp.Client(auth=(_cfg.RAZORPAY_KEY_ID, _cfg.RAZORPAY_KEY_SECRET))
                        actual_pay_id = self._resolve_razorpay_payment_id(rzp_client, rzp_payment_id)
                        refund_data = {
                            "amount": int(round(float(order.total_amount) * 100)),  # paise
                            "reverse_all": 1,
                            "notes": {
                                "order_id": str(order.id),
                                "reason": cancellation_reason or "Order cancelled by restaurant"
                            }
                        }
                        refund_res = rzp_client.payment.refund(actual_pay_id, refund_data)
                        if refund_res and "id" in refund_res:
                            order.refund_id = refund_res["id"]
                    else:
                        order.refund_id = f"rfnd_mock_{uuid.uuid4().hex[:12]}"
                    order.payment_status = "refunded"
                    print(f"\033[92m\033[1m✅ [AUTO-REFUND SUCCESS] Order {order_ref} → ₹{float(order.total_amount):.2f} refunded on cancel (Payment ID: {rzp_payment_id}, Refund ID: {order.refund_id})\033[0m")
                    # Send WhatsApp refund notification
                    if order.customer_phone:
                        try:
                            from app.services.whatsapp_service import WhatsAppClient
                            wa = WhatsAppClient()
                            shop_res = await self.db.execute(select(Shop.name).where(Shop.id == shop_id))
                            shop_name = shop_res.scalar_one_or_none() or "Restaurant"
                            order_num = str(order.daily_order_number or order.id.hex[:8]).upper()
                            await asyncio.to_thread(
                                wa.send_order_refund_template,
                                phone_number=order.customer_phone,
                                customer_name=order.customer_name or "Customer",
                                order_number=order_num,
                                shop_name=shop_name,
                                items_summary="Order cancelled by restaurant — full refund initiated",
                                refund_amount=f"{float(order.total_amount):.2f}",
                                order_id_tag=f"#{order_num}",
                                refund_method="Online",
                                timeline_days="5-7",
                                shop_id=str(shop_id),
                                order_id=str(order.id),
                            )
                        except Exception as wa_e:
                            print(f"\033[91m[WHATSAPP] Failed to send cancel+refund notification: {wa_e}\033[0m")
                except Exception as refund_err:
                    print(f"\033[91m\033[1m❌ [AUTO-REFUND FAILED] Order {order_ref} → {refund_err}\033[0m")
                    # Flag for manual review / retry physical button — do NOT block the cancellation!
                    order.payment_status = "refund_failed"

            # Case B: Customer is mid-payment (Razorpay checkout open, not yet captured)
            # Mark cancelled now — when the customer completes payment and the Razorpay
            # verify_public_order_payment endpoint fires, it already detects CANCELLED status
            # and auto-refunds the captured amount immediately.
            elif is_online and is_mid_payment:
                print(f"\033[93m\033[1m⚠️  [ADMIN CANCEL MID-PAYMENT] Order {order_ref} cancelled while customer was paying. Razorpay verify will auto-refund on confirmation.\033[0m")

        order.order_status = status
        
        if status == "PAYMENT_PENDING" and order.payment_method not in ["cash", "cash_on_delivery", "counter"]:
            from datetime import timedelta, datetime, timezone
            order.payment_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        else:
            # Clear expiry if we move past PAYMENT_PENDING or for cash orders
            order.payment_expires_at = None
        
        if status == "CANCELLED":
            order.cancellation_reason = cancellation_reason or order.cancellation_reason or "VENDOR_REJECTED"

        # Restore customer discount usages if order is cancelled or rejected
        if status in ["CANCELLED", "REJECTED"]:
            await self._restore_discount_usages_for_order(order)

        # Award 0.15 Contest Credits if completed order total >= ₹100 & mark all active items as completed (served)
        if status in ["COMPLETED", "DELIVERED"]:
            for it in (order.items or []):
                if not it.is_cancelled:
                    it.is_completed = True
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

        # Broadcast live to shop and customer with 0 delay
        await self._broadcast_order_live(
            order=order,
            event_type="ORDER_STATUS",
            title=f"Order #{order.id.hex[:8]} {status.capitalize()}",
            message=f"Order status has been updated to {status}."
        )

        # Send WhatsApp template notifications
        if status in ["ACCEPTED", "PAYMENT_PENDING"] and str(order.payment_status or "").lower() != "paid":
            await self._send_order_accepted_payment_required_whatsapp_notification(order)
        elif status == "PAID" or str(order.payment_status or "").lower() == "paid":
            await self._send_order_status_whatsapp_notification(order)

        return order

    async def _send_order_accepted_payment_required_whatsapp_notification(self, order: Order, shop_name: Optional[str] = None):
        """Send 'menukit_order_accepted_payment_required_template' WhatsApp template to customer when admin accepts order and online payment is pending."""
        if not order or not order.customer_phone:
            return

        # Check 1: Only send if payment is pending (not already paid)
        is_paid = str(order.payment_status or "").lower() == "paid"
        if is_paid:
            return

        # Check 2: Only send for online payment methods
        payment_method = str(order.payment_method or "").lower()
        if payment_method in ["cash", "counter", "cash_on_delivery"]:
            return

        # Check 3: Do not send for cancelled or rejected orders
        status = str(order.order_status or "").upper()
        if status in ["CANCELLED", "REJECTED"]:
            return

        try:
            currency = "₹"
            if hasattr(order, "shop") and order.shop:
                if hasattr(order.shop, "settings") and order.shop.settings and getattr(order.shop.settings, "currency", None):
                    currency = order.shop.settings.currency
                shop_name = shop_name or getattr(order.shop, "name", None)
            else:
                shop_res = await self.db.execute(
                    select(Shop).options(selectinload(Shop.settings)).where(Shop.id == order.shop_id)
                )
                shop_obj = shop_res.scalar_one_or_none()
                if shop_obj:
                    shop_name = shop_name or shop_obj.name
                    if shop_obj.settings and shop_obj.settings.currency:
                        currency = shop_obj.settings.currency

            shop_name = shop_name or "Restaurant"
            amt_val = float(order.total_amount or 0.0)
            if str(order.payment_method or "").lower() == "online":
                plat_fee = round(amt_val * 0.02, 2)
                pg_fee = round(amt_val * 0.03, 2)
                gst_on_fee = round(pg_fee * 0.18, 2)
                grand_total = round(amt_val + plat_fee + pg_fee + gst_on_fee, 2)
            else:
                grand_total = amt_val

            formatted_amount = f"{currency}{grand_total:.2f}"
            order_num = str(order.daily_order_number or order.id.hex[:8])
            customer_name = order.customer_name or "Customer"

            def _send_wa_payment_req():
                try:
                    from app.services.whatsapp_service import WhatsAppClient
                    wa = WhatsAppClient()
                    wa.send_order_accepted_payment_required_template(
                        phone_number=order.customer_phone,
                        customer_name=customer_name,
                        order_number=order_num,
                        shop_name=shop_name,
                        order_amount=formatted_amount,
                        shop_id=str(order.shop_id),
                        order_id=str(order.id),
                    )
                except Exception as ex:
                    print(f"Failed to send order accepted payment required WhatsApp: {ex}")

            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.run_in_executor(None, _send_wa_payment_req)
            except RuntimeError:
                _send_wa_payment_req()
        except Exception as e:
            print(f"Error initiating WhatsApp payment required notification: {e}")

    async def _send_order_status_whatsapp_notification(self, order: Order, shop_name: Optional[str] = None):
        """Send 'menukit_order_created' WhatsApp template to customer when order is Paid."""
        if not order or not order.customer_phone:
            return

        # STRICT GUARD 1: Prevent duplicate notifications for the same order
        if getattr(order, "whatsapp_sent", False):
            return

        # STRICT GUARD 2: Only send WhatsApp message if order payment is confirmed ('paid')
        is_paid = str(order.payment_status or "").lower() == "paid"
        if not is_paid:
            return

        # STRICT GUARD 3: Do not send for cancelled or rejected orders
        status = str(order.order_status or "").upper()
        if status in ["CANCELLED", "REJECTED"]:
            return

        # Mark as sent immediately to avoid duplicate triggers across concurrent events
        order.whatsapp_sent = True
        try:
            self.db.add(order)
            await self.db.flush()
        except Exception as e:
            print(f"Failed to flush order.whatsapp_sent: {e}")

        try:
            currency = "₹"
            if hasattr(order, "shop") and order.shop:
                if hasattr(order.shop, "settings") and order.shop.settings and getattr(order.shop.settings, "currency", None):
                    currency = order.shop.settings.currency
                shop_name = shop_name or getattr(order.shop, "name", None)
            else:
                shop_res = await self.db.execute(
                    select(Shop).options(selectinload(Shop.settings)).where(Shop.id == order.shop_id)
                )
                shop_obj = shop_res.scalar_one_or_none()
                if shop_obj:
                    shop_name = shop_name or shop_obj.name
                    if shop_obj.settings and shop_obj.settings.currency:
                        currency = shop_obj.settings.currency

            shop_name = shop_name or "Restaurant"
            raw_phone = order.customer_phone
            clean_phone = "".join(filter(str.isdigit, raw_phone))
            if not clean_phone:
                return
            if len(clean_phone) == 10:
                clean_phone = f"91{clean_phone}"

            amt_val = float(order.total_amount or 0.0)
            if str(order.payment_method or "").lower() == "online":
                plat_fee = round(amt_val * 0.02, 2)
                pg_fee = round(amt_val * 0.03, 2)
                gst_on_fee = round(pg_fee * 0.18, 2)
                grand_total = round(amt_val + plat_fee + pg_fee + gst_on_fee, 2)
            else:
                grand_total = amt_val

            formatted_amount = f"{currency}{grand_total:.2f}"
            bill_id = f"#{order.daily_order_number}" if order.daily_order_number else order.id.hex[:8].upper()
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

        await self.db.flush()
        await self.db.refresh(order, attribute_names=["items"])

        # Re-compute total_amount based on all active items and shop tax settings
        active_items_subtotal = sum(
            float(it.price or 0.0) * int(it.quantity or 1)
            for it in (order.items or [])
            if not it.is_cancelled
        )
        settings_stmt = select(ShopSettings).where(ShopSettings.shop_id == order.shop_id)
        settings_res = await self.db.execute(settings_stmt)
        shop_st = settings_res.scalar_one_or_none()

        tax_amount = 0.0
        if shop_st and shop_st.gst_enabled and not shop_st.inclusive_tax:
            cgst_rate = float(shop_st.cgst_rate or 0.0)
            sgst_rate = float(shop_st.sgst_rate or 0.0)
            cgst = round(active_items_subtotal * (cgst_rate / 100.0), 2)
            sgst = round(active_items_subtotal * (sgst_rate / 100.0), 2)
            tax_amount = round(cgst + sgst, 2)

        order.total_amount = round(active_items_subtotal + tax_amount, 2)
        await self.db.flush()
        await self._broadcast_order_live(order, event_type="ORDER_UPDATED")
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
        await self._broadcast_order_live(order, event_type="ORDER_UPDATED")
        return order

    async def _process_online_refund(
        self,
        order: Order,
        refund_amount: float,
        note: str,
        items_summary: Optional[str] = None,
        cancel_reason: Optional[str] = None
    ) -> bool:
        """Process partial or full online refund via Razorpay (excluding platform fees/charges)."""
        if refund_amount <= 0:
            return False

        order_ref = f"#{order.daily_order_number or order.id.hex[:8]}"

        # Strict Rule 1: Only refund if the order was ACTUALLY paid
        if str(order.payment_status or "").lower() not in ["paid", "partially_refunded"]:
            print(f"\033[93m\033[1m⚠️ [REFUND SKIPPED] Order {order_ref} ➔ Unpaid order (status: '{order.payment_status}')\033[0m")
            return False

        # Strict Rule 2: Payment method must be online via gateway
        if str(order.payment_method or "").lower() != "online":
            print(f"\033[93m\033[1m⚠️ [REFUND SKIPPED] Order {order_ref} ➔ Payment method is '{order.payment_method}', not online gateway\033[0m")
            return False

        print(f"\033[96m\033[1m💸 [ONLINE REFUND INITIATED] Order {order_ref} ➔ Amount: ₹{refund_amount:.2f} | Reason: {note}\033[0m")

        settings = get_settings()

        # Only mock if payment ID starts with 'pay_mock_' or 'order_mock_'
        is_mock_payment = bool(
            order.payment_session_id and (
                order.payment_session_id.startswith("pay_mock_") or 
                order.payment_session_id.startswith("order_mock_")
            )
        )
        if is_mock_payment:
            print(f"\033[92m\033[1m✅ [MOCK REFUND SUCCESS] Order {order_ref} ➔ ₹{refund_amount:.2f} refunded (Mock Mode) | Note: {note}\033[0m")
            return True

        rzp_payment_id = order.payment_session_id or order.razorpay_order_id
        if not rzp_payment_id:
            print(f"\033[91m\033[1m❌ [REFUND FAILED] Order {order_ref} ➔ Missing payment_session_id / razorpay_order_id\033[0m")
            return False

        if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
            print(f"\033[91m\033[1m❌ [REFUND FAILED] Order {order_ref} ➔ Razorpay API credentials not configured\033[0m")
            return False

        try:
            import razorpay
            client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
            actual_pay_id = self._resolve_razorpay_payment_id(client, rzp_payment_id)

            # Amount in paise (multiply by 100)
            amount_paise = int(round(refund_amount * 100))

            # Fetch payment to check actual captured balance on Razorpay
            try:
                pay_obj = client.payment.fetch(actual_pay_id)
                captured_paise = int(pay_obj.get("amount", 0)) - int(pay_obj.get("amount_refunded", 0))
                if captured_paise > 0 and amount_paise > captured_paise:
                    print(f"\033[93m\033[1m⚠️ [REFUND CLAMPED] Order {order_ref} ➔ Clamping refund from ₹{refund_amount:.2f} to captured balance ₹{captured_paise/100:.2f}\033[0m")
                    amount_paise = captured_paise
            except Exception as f_err:
                print(f"Could not fetch payment balance from Razorpay: {f_err}")

            refund_resp = client.payment.refund(actual_pay_id, {
                "amount": amount_paise,
                "reverse_all": 1,
                "notes": {
                    "reason": note[:250],
                    "order_id": str(order.id),
                    "customer_phone": order.customer_phone or ""
                }
            })
            refund_id = refund_resp.get('id', 'N/A')
            order.refund_id = refund_id
            order.payment_status = "refunded"
            print(f"\033[92m\033[1m✅ [RAZORPAY REFUND SUCCESS] Order {order_ref} ➔ ₹{amount_paise/100:.2f} refunded (Payment ID: {actual_pay_id}, Refund ID: {refund_id})\033[0m")

            # Send WhatsApp refund notification using 'menukit_order_refund_template'
            if order.customer_phone:
                def _send_wa_refund():
                    try:
                        from app.services.whatsapp_service import WhatsAppClient
                        wa = WhatsAppClient()
                        cust_name = order.customer_name or "Customer"
                        shop_name = getattr(order.shop, "name", None) if hasattr(order, "shop") and order.shop else "Restaurant"
                        order_num = str(order.daily_order_number or order.id.hex[:8])
                        order_id_tag = order_num

                        currency = "₹"
                        if hasattr(order, "shop") and order.shop:
                            if hasattr(order.shop, "settings") and order.shop.settings and getattr(order.shop.settings, "currency", None):
                                currency = order.shop.settings.currency

                        formatted_amt = f"{amount_paise/100:.2f}" if not float(amount_paise/100).is_integer() else f"{int(amount_paise/100)}"
                        summary_text = items_summary or f"Cancelled Items = {currency}{formatted_amt}"
                        reason_text = cancel_reason or note or "Cancelled by request"

                        wa.send_order_refund_template(
                            phone_number=order.customer_phone,
                            customer_name=cust_name,
                            order_number=order_num,
                            shop_name=shop_name,
                            items_summary=summary_text,
                            cancel_reason=reason_text,
                            refund_amount=formatted_amt,
                            order_id_tag=order_id_tag,
                            refund_method="Online",
                            timeline_days="5-7",
                            shop_id=str(order.shop_id),
                            order_id=str(order.id),
                        )
                    except Exception as wa_ex:
                        print(f"Failed to dispatch WhatsApp refund notification: {wa_ex}")

                try:
                    loop = asyncio.get_running_loop()
                    loop.run_in_executor(None, _send_wa_refund)
                except RuntimeError:
                    _send_wa_refund()

            return True
        except Exception as err:
            print(f"[Razorpay Refund Error] Failed to refund Rs.{refund_amount:.2f} for Order #{order.id}: {err}")
            order.payment_status = "refund_failed"
            return False

    async def toggle_order_item_cancel(
        self, order_id: uuid.UUID, item_id: uuid.UUID, shop_id: uuid.UUID, reason: Optional[str] = None
    ) -> Order:
        """Cancel an individual order item, refund product price if paid online, and permanently block recovery for refunded items."""
        result = await self.db.execute(
            select(Order)
            .options(
                selectinload(Order.items),
                selectinload(Order.shop).selectinload(Shop.settings)
            )
            .where(Order.id == order_id, Order.shop_id == shop_id)
        )
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        # Block 1: If order is already marked CANCELLED or REJECTED, block any further item operations or duplicate refunds
        if str(order.order_status or "").upper() in ["CANCELLED", "REJECTED"]:
            raise HTTPException(
                status_code=400,
                detail="This order is already cancelled. Item recovery or duplicate refunds are strictly blocked."
            )

        item = next((it for it in order.items if it.id == item_id), None)
        if not item:
            raise HTTPException(status_code=404, detail="Order item not found")

        # Calculate ONLY the product/item price (unit price * quantity) — strictly excluding platform charges
        item_product_amount = float(item.price or 0.0) * int(item.quantity or 1)
        is_paid = str(order.payment_status or "").lower() == "paid"
        is_paid_online = is_paid and str(order.payment_method or "").lower() == "online"

        # Block 2: If item is ALREADY cancelled
        if item.is_cancelled:
            if str(item.cancellation_reason or "").startswith("Replaced with"):
                raise HTTPException(
                    status_code=400,
                    detail="This item was replaced with another item and cannot be restored."
                )
            if is_paid:
                raise HTTPException(
                    status_code=400,
                    detail="This item was already cancelled and refunded to the customer. It cannot be recovered."
                )
            # Unpaid order item restore
            item.is_cancelled = False
            item.cancellation_reason = None
            broadcast_title = "Item Restored"
            broadcast_msg = f"Item '{item.name}' has been restored to your order."
            event_type = "ORDER_UPDATED"
        else:
            # Cancel the item
            item.is_cancelled = True
            item.is_completed = False
            item.cancellation_reason = reason or "Cancelled by staff"

            broadcast_title = "Item Cancelled"
            broadcast_msg = f"Item '{item.name}' was cancelled."
            event_type = "ORDER_UPDATED"

            # Auto-refund ONLY the product price if order was paid online
            if is_paid_online and item_product_amount > 0:
                currency = "₹"
                if hasattr(order, "shop") and order.shop and hasattr(order.shop, "settings") and order.shop.settings:
                    currency = getattr(order.shop.settings, "currency", "₹") or "₹"

                amt_str = f"{item_product_amount:.2f}" if not float(item_product_amount).is_integer() else f"{int(item_product_amount)}"
                chosen_reason = item.cancellation_reason or "Cancelled by staff"
                item_summary = f"{item.name} x {item.quantity} = {currency}{amt_str}"

                await self._process_online_refund(
                    order=order,
                    refund_amount=item_product_amount,
                    note=f"Item '{item.name}' cancelled (Product price refund)",
                    items_summary=item_summary,
                    cancel_reason=chosen_reason
                )
                broadcast_title = "Item Cancelled — Refund Initiated"
                broadcast_msg = f"Item '{item.name}' was cancelled. Product price of {currency}{item_product_amount:.2f} has been refunded to your original payment method."
                event_type = "ITEM_CANCELLED_REFUND"

            # Check and restore discount usage if this was the only qualifying item for a discount
            await self._restore_discount_usages_for_item(order, item.id, item.menu_item_id)

        # Re-compute total_amount based on all active items and shop tax settings
        active_items_subtotal = sum(
            float(it.price or 0.0) * int(it.quantity or 1)
            for it in (order.items or [])
            if not it.is_cancelled
        )
        settings_stmt = select(ShopSettings).where(ShopSettings.shop_id == order.shop_id)
        settings_res = await self.db.execute(settings_stmt)
        shop_st = settings_res.scalar_one_or_none()
        
        tax_amount = 0.0
        if shop_st and shop_st.gst_enabled and not shop_st.inclusive_tax:
            cgst_rate = float(shop_st.cgst_rate or 0.0)
            sgst_rate = float(shop_st.sgst_rate or 0.0)
            total_tax_rate = cgst_rate + sgst_rate
            tax_amount = round(active_items_subtotal * (total_tax_rate / 100.0), 2)

        order.total_amount = round(active_items_subtotal + tax_amount, 2)

        # Automatic Order Status Transition:
        # If all items in the order are now cancelled, automatically mark the whole order as CANCELLED while preserving total_amount.
        active_items = [it for it in (order.items or []) if not it.is_cancelled]
        if not active_items and len(order.items or []) > 0:
            order.order_status = "CANCELLED"
            order.cancellation_reason = reason or "All items cancelled by restaurant"
            if not order.total_amount or float(order.total_amount) <= 0.0:
                all_items_subtotal = sum(
                    float(it.price or 0.0) * int(it.quantity or 1)
                    for it in (order.items or [])
                )
                order.total_amount = round(all_items_subtotal, 2)
            if is_paid_online:
                if not order.refund_id or str(order.payment_status or "").lower() == "refund_failed":
                    order.payment_status = "refund_failed"
                    broadcast_title = "Order Cancelled — Awaiting Refund"
                    broadcast_msg = f"All items in Order #{order.daily_order_number or order.id.hex[:8]} were cancelled. Online refund is awaiting retry."
                    event_type = "ORDER_UPDATED"
                else:
                    order.payment_status = "refunded"
                    broadcast_title = "Order Cancelled — Refund Processed"
                    broadcast_msg = f"All items in Order #{order.daily_order_number or order.id.hex[:8]} were cancelled. Product price has been refunded (charges excluded)."
                    event_type = "ORDER_CANCELLED_REFUND"
            else:
                broadcast_title = "Order Cancelled"
                broadcast_msg = f"All items in Order #{order.daily_order_number or order.id.hex[:8]} were cancelled."
                event_type = "ORDER_CANCELLED"

        order.version = (order.version or 1) + 1
        await self.db.flush()
        await self._broadcast_order_live(
            order,
            event_type=event_type,
            title=broadcast_title,
            message=broadcast_msg
        )
        return order

    async def replace_order_item(
        self,
        order_id: uuid.UUID,
        item_id: uuid.UUID,
        shop_id: uuid.UUID,
        replace_data: Any,
    ) -> Order:
        """Atomically cancel an order item with replacement note, append replacement item, and handle price difference refunds/payments."""
        result = await self.db.execute(
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.id == order_id, Order.shop_id == shop_id)
        )
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        if str(order.order_status or "").upper() in ["COMPLETED", "CANCELLED", "REJECTED"]:
            raise HTTPException(status_code=400, detail="Cannot modify items of a completed or cancelled order")

        old_item = next((it for it in order.items if it.id == item_id), None)
        if not old_item:
            raise HTTPException(status_code=404, detail="Original order item not found")

        if old_item.is_cancelled:
            raise HTTPException(status_code=400, detail="Cannot replace an item that has already been cancelled.")

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
        await self.db.flush()
        await self.db.refresh(order, attribute_names=["items"])

        # Capture previous order total before re-calculating
        previous_order_total = float(order.total_amount or 0.0)

        # Re-compute total_amount based on all active items and shop tax settings
        active_items_subtotal = sum(
            float(it.price or 0.0) * int(it.quantity or 1)
            for it in (order.items or [])
            if not it.is_cancelled
        )
        
        # Load shop settings for exclusive tax
        settings_stmt = select(ShopSettings).where(ShopSettings.shop_id == order.shop_id)
        settings_res = await self.db.execute(settings_stmt)
        shop_st = settings_res.scalar_one_or_none()
        
        tax_amount = 0.0
        if shop_st and shop_st.gst_enabled and not shop_st.inclusive_tax:
            cgst_rate = float(shop_st.cgst_rate or 0.0)
            sgst_rate = float(shop_st.sgst_rate or 0.0)
            total_tax_rate = cgst_rate + sgst_rate
            tax_amount = round(active_items_subtotal * (total_tax_rate / 100.0), 2)

        order.total_amount = round(active_items_subtotal + tax_amount, 2)

        from app.core.pricing import calculate_order_pricing, calculate_replacement

        # 3. Calculate price difference accounting for platform & payment gateway fees if paid online
        is_paid = str(order.payment_status or "").lower() == "paid"
        is_paid_online = is_paid and str(order.payment_method or "").lower() == "online"

        if is_paid_online:
            orig_paid_amount = calculate_order_pricing(previous_order_total, is_online=True).total_payable
        else:
            orig_paid_amount = previous_order_total

        rep_calc = calculate_replacement(
            original_paid_amount=orig_paid_amount,
            new_subtotal=float(order.total_amount),
            old_subtotal=previous_order_total,
            is_online=is_paid_online
        )
        price_diff = rep_calc.difference
        refund_amount = rep_calc.refund_amount
        additional_payment = rep_calc.additional_payment

        broadcast_title = "Item Replaced"
        broadcast_msg = f"Item '{old_item.name}' was replaced with '{replace_data.name}'."
        event_type = "ITEM_REPLACED"

        if is_paid:
            currency = "₹"
            if shop_st and shop_st.currency:
                currency = shop_st.currency

            if price_diff > 0:
                # Scenario 1: Replacing item is HIGHER in price -> extra difference due from customer
                if is_paid_online:
                    order.payment_status = "pending"  # Customer must pay remaining difference
                    order.whatsapp_sent = False        # Allow sending updated bill WhatsApp when payment completes
                    await self._send_order_accepted_payment_required_whatsapp_notification(order)

                broadcast_title = "Item Replaced — Payment Difference Due"
                broadcast_msg = f"Item '{old_item.name}' was replaced with '{replace_data.name}'. Additional difference of {currency}{additional_payment:.2f} is due. Please complete payment online."
                event_type = "ITEM_REPLACED_EXTRA_PAYMENT"
            elif price_diff < 0:
                # Scenario 2: Replacing item is LOWER in price -> refund the net difference amount (accounting for new item fees)
                if is_paid_online and refund_amount > 0:
                    amt_str = f"{refund_amount:.2f}" if not float(refund_amount).is_integer() else f"{int(refund_amount)}"
                    replace_reason = replace_data.reason or "Item replaced"
                    replace_summary = f"Replaced with {replace_data.name} = {currency}{amt_str}"

                    await self._process_online_refund(
                        order=order,
                        refund_amount=refund_amount,
                        note=f"Replaced '{old_item.name}' with '{replace_data.name}' (Price difference refund)",
                        items_summary=replace_summary,
                        cancel_reason=replace_reason
                    )
                    broadcast_title = "Item Replaced — Refund Initiated"
                    broadcast_msg = f"Item '{old_item.name}' was replaced with '{replace_data.name}'. {currency}{refund_amount:.2f} (price difference) has been refunded to your original payment method."
                    event_type = "ITEM_REPLACED_REFUND"
                else:
                    broadcast_title = "Item Replaced — Change Due"
                    broadcast_msg = f"Item '{old_item.name}' was replaced with '{replace_data.name}'. Balance {currency}{refund_amount:.2f} to be refunded at the counter."
                    event_type = "ITEM_REPLACED_REFUND"

        order.version = (order.version or 1) + 1
        await self.db.flush()
        await self._handle_replacement_discount_usage(order, old_item.menu_item_id, new_menu_item_id)
        await self._broadcast_order_live(
            order,
            event_type=event_type,
            title=broadcast_title,
            message=broadcast_msg
        )
        return order

    async def preview_replace_order_item(
        self,
        order_id: uuid.UUID,
        item_id: uuid.UUID,
        shop_id: uuid.UUID,
        replace_data: Any,
    ) -> dict:
        """Calculate hypothetical order state and price difference / refund preview without modifying DB."""
        result = await self.db.execute(
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.id == order_id, Order.shop_id == shop_id)
        )
        order = result.scalar_one_or_none()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        old_item = next((it for it in order.items if it.id == item_id), None)
        if not old_item:
            raise HTTPException(status_code=404, detail="Original order item not found")

        previous_order_total = float(order.total_amount or 0.0)

        # Build hypothetical new items subtotal
        new_quantity = int(replace_data.quantity or 1)
        new_price = float(replace_data.price or 0.0)
        new_item_amount = new_price * new_quantity

        # Sum active items except old_item
        active_items_subtotal = sum(
            float(it.price or 0.0) * int(it.quantity or 1)
            for it in (order.items or [])
            if not it.is_cancelled and it.id != item_id
        ) + new_item_amount

        # Load shop settings for exclusive tax
        settings_stmt = select(ShopSettings).where(ShopSettings.shop_id == order.shop_id)
        settings_res = await self.db.execute(settings_stmt)
        shop_st = settings_res.scalar_one_or_none()

        tax_amount = 0.0
        if shop_st and shop_st.gst_enabled and not shop_st.inclusive_tax:
            cgst_rate = float(shop_st.cgst_rate or 0.0)
            sgst_rate = float(shop_st.sgst_rate or 0.0)
            total_tax_rate = cgst_rate + sgst_rate
            tax_amount = round(active_items_subtotal * (total_tax_rate / 100.0), 2)

        new_subtotal = round(active_items_subtotal + tax_amount, 2)

        from app.core.pricing import calculate_order_pricing, calculate_replacement
        is_paid = str(order.payment_status or "").lower() == "paid"
        is_paid_online = is_paid and str(order.payment_method or "").lower() == "online"

        if is_paid_online:
            orig_paid_amount = calculate_order_pricing(previous_order_total, is_online=True).total_payable
        else:
            orig_paid_amount = previous_order_total

        rep_calc = calculate_replacement(
            original_paid_amount=orig_paid_amount,
            new_subtotal=new_subtotal,
            old_subtotal=previous_order_total,
            is_online=is_paid_online
        )

        return rep_calc.model_dump()

    async def _record_discount_usages(self, order: Order, applied_ids: list, applied_codes: list):
        """Validate that customer has not used any of these discounts, and record discount usage."""
        from app.models.discount import Discount, DiscountRedemption, CustomerDiscountCode
        from app.api.v1.public import _get_phone_variants
        from datetime import datetime, timezone
        from sqlalchemy import or_, func

        cust_phone = (order.customer_phone or "").strip()
        phone_variants = _get_phone_variants(cust_phone) if cust_phone else []

        applied_disc_ids = [uuid.UUID(str(x)) for x in (applied_ids or []) if x]
        applied_disc_codes = [str(c).strip().upper() for c in (applied_codes or []) if c]

        if not applied_disc_ids and not applied_disc_codes:
            return

        # 1. Fetch discounts
        disc_query = select(Discount).where(
            or_(
                Discount.id.in_(applied_disc_ids) if applied_disc_ids else False,
                func.upper(Discount.code).in_(applied_disc_codes) if applied_disc_codes else False
            )
        )
        disc_res = await self.db.execute(disc_query)
        discounts = disc_res.scalars().all()

        now = datetime.now(timezone.utc)

        for disc in discounts:
            # Check if customer has already used this discount
            if phone_variants:
                last4 = cust_phone[-4:].upper() if len(cust_phone) >= 4 else ""
                check_stmt = select(DiscountRedemption).where(
                    DiscountRedemption.shop_id == order.shop_id,
                    DiscountRedemption.discount_id == disc.id,
                    DiscountRedemption.status == "active",
                    or_(
                        DiscountRedemption.customer_identifier.in_(phone_variants),
                        func.upper(DiscountRedemption.code).like(f"%-{last4}") if last4 else False
                    )
                )
                existing_use = (await self.db.execute(check_stmt)).scalars().first()
                if existing_use:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Discount already used. The offer '{disc.title}' has already been used and cannot be reused."
                    )

            # Record redemption
            code_str = disc.code or disc.title
            # Check CustomerDiscountCode
            if phone_variants:
                assigned_stmt = select(CustomerDiscountCode).where(
                    CustomerDiscountCode.shop_id == order.shop_id,
                    CustomerDiscountCode.discount_id == disc.id,
                    CustomerDiscountCode.customer_identifier.in_(phone_variants)
                )
                assigned_code = (await self.db.execute(assigned_stmt)).scalars().first()
                if assigned_code:
                    code_str = assigned_code.code
                    assigned_code.is_redeemed = True
                    assigned_code.redeemed_at = now

            # Find matching item if applies_to == 'items'
            matched_item_id = None
            if disc.applies_to == "items" and disc.target_ids:
                items_to_check = order.__dict__.get("items", None)
                if items_to_check is None:
                    from app.models.order import OrderItem
                    i_res = await self.db.execute(select(OrderItem).where(OrderItem.order_id == order.id))
                    items_to_check = i_res.scalars().all()
                target_strs = [str(t) for t in disc.target_ids]
                for it in (items_to_check or []):
                    # 1. Whole item match
                    if str(it.menu_item_id) in target_strs:
                        matched_item_id = it.menu_item_id
                        it.applied_discount_id = disc.id
                        break
                    # 2. Specific variant match: "itemId::variantName"
                    it_var_name = None
                    if it.variant_info and isinstance(it.variant_info, dict):
                        it_var_name = it.variant_info.get("name")
                    if it_var_name:
                        v_norm = str(it_var_name).strip().lower()
                        for tid in target_strs:
                            if tid.startswith(f"{it.menu_item_id}::"):
                                target_var = tid.split("::", 1)[1].strip().lower()
                                if target_var == v_norm:
                                    matched_item_id = it.menu_item_id
                                    it.applied_discount_id = disc.id
                                    break
                    if matched_item_id:
                        break

            redemption = DiscountRedemption(
                id=uuid.uuid4(),
                discount_id=disc.id,
                shop_id=order.shop_id,
                code=code_str,
                redeemed_at=now,
                customer_identifier=cust_phone or "Guest",
                order_id=order.id,
                status="active",
                menu_item_id=matched_item_id
            )
            self.db.add(redemption)

    async def _restore_discount_usages_for_order(self, order: Order):
        """Restore all discount usages when an entire order is rejected or cancelled."""
        from app.models.discount import DiscountRedemption, CustomerDiscountCode
        from sqlalchemy import update

        redemptions_res = await self.db.execute(
            select(DiscountRedemption).where(
                DiscountRedemption.order_id == order.id,
                DiscountRedemption.status == "active"
            )
        )
        redemptions = redemptions_res.scalars().all()
        for r in redemptions:
            r.status = "restored"
            # Unmark customer discount code
            pv = set()
            if order.customer_phone:
                raw_p = str(order.customer_phone).strip()
                clean_p = "".join(filter(str.isdigit, raw_p))
                pv.add(raw_p)
                pv.add(clean_p)
                if len(clean_p) >= 10:
                    pv.add(clean_p[-10:])
                    pv.add(f"+91{clean_p[-10:]}")
                    pv.add(f"91{clean_p[-10:]}")
            if r.customer_identifier:
                raw_c = str(r.customer_identifier).strip()
                clean_c = "".join(filter(str.isdigit, raw_c))
                pv.add(raw_c)
                pv.add(clean_c)
                if len(clean_c) >= 10:
                    pv.add(clean_c[-10:])
                    pv.add(f"+91{clean_c[-10:]}")
                    pv.add(f"91{clean_c[-10:]}")
            if pv:
                await self.db.execute(
                    update(CustomerDiscountCode)
                    .where(
                        CustomerDiscountCode.shop_id == r.shop_id,
                        CustomerDiscountCode.discount_id == r.discount_id,
                        CustomerDiscountCode.customer_identifier.in_(list(pv))
                    )
                    .values(is_redeemed=False, redeemed_at=None)
                )

    async def _restore_discount_usages_for_item(self, order: Order, item_id: uuid.UUID, menu_item_id: uuid.UUID):
        """Restore discount usage when a discounted item is cancelled, if no other active items qualify."""
        from app.models.discount import Discount, DiscountRedemption, CustomerDiscountCode
        from sqlalchemy import update

        redemptions_res = await self.db.execute(
            select(DiscountRedemption)
            .options(selectinload(DiscountRedemption.discount))
            .where(
                DiscountRedemption.order_id == order.id,
                DiscountRedemption.status == "active"
            )
        )
        redemptions = redemptions_res.scalars().all()

        active_items = [it for it in (order.items or []) if not it.is_cancelled and it.id != item_id]

        for r in redemptions:
            disc = r.discount
            if not disc:
                continue

            # If discount was item-specific
            if disc.applies_to == "items" and disc.target_ids:
                target_strs = [str(t) for t in disc.target_ids]
                has_other_match = False
                for it in active_items:
                    if str(it.menu_item_id) in target_strs:
                        has_other_match = True
                        break
                    it_var_name = None
                    if it.variant_info and isinstance(it.variant_info, dict):
                        it_var_name = it.variant_info.get("name")
                    if it_var_name:
                        v_norm = str(it_var_name).strip().lower()
                        for tid in target_strs:
                            if tid.startswith(f"{it.menu_item_id}::"):
                                target_var = tid.split("::", 1)[1].strip().lower()
                                if target_var == v_norm:
                                    has_other_match = True
                                    break
                    if has_other_match:
                        break

                if not has_other_match:
                    r.status = "restored"
                    if r.customer_identifier:
                        await self.db.execute(
                            update(CustomerDiscountCode)
                            .where(
                                CustomerDiscountCode.shop_id == r.shop_id,
                                CustomerDiscountCode.discount_id == r.discount_id,
                                CustomerDiscountCode.customer_identifier == r.customer_identifier
                            )
                            .values(is_redeemed=False, redeemed_at=None)
                        )
            elif disc.applies_to == "category" and disc.target_ids:
                # Check if any other item matches category
                from app.models.menu_item import MenuItem
                active_menu_ids = [it.menu_item_id for it in active_items]
                has_cat_match = False
                if active_menu_ids:
                    m_res = await self.db.execute(select(MenuItem.category_id).where(MenuItem.id.in_(active_menu_ids)))
                    cat_ids = [str(c) for c in m_res.scalars().all()]
                    has_cat_match = any(c in [str(t) for t in disc.target_ids] for c in cat_ids)
                if not has_cat_match:
                    r.status = "restored"
                    if r.customer_identifier:
                        await self.db.execute(
                            update(CustomerDiscountCode)
                            .where(
                                CustomerDiscountCode.shop_id == r.shop_id,
                                CustomerDiscountCode.discount_id == r.discount_id,
                                CustomerDiscountCode.customer_identifier == r.customer_identifier
                            )
                            .values(is_redeemed=False, redeemed_at=None)
                        )
            elif len(active_items) == 0:
                # Storewide discount but all items are cancelled
                r.status = "restored"
                if r.customer_identifier:
                    await self.db.execute(
                        update(CustomerDiscountCode)
                        .where(
                            CustomerDiscountCode.shop_id == r.shop_id,
                            CustomerDiscountCode.discount_id == r.discount_id,
                            CustomerDiscountCode.customer_identifier == r.customer_identifier
                        )
                        .values(is_redeemed=False, redeemed_at=None)
                    )

    async def _handle_replacement_discount_usage(self, order: Order, old_menu_item_id: uuid.UUID, new_menu_item_id: uuid.UUID):
        """Recalculate or restore discount usage when an item is replaced."""
        from app.models.discount import Discount, DiscountRedemption, CustomerDiscountCode
        from app.models.menu_item import MenuItem
        from sqlalchemy import update

        redemptions_res = await self.db.execute(
            select(DiscountRedemption)
            .options(selectinload(DiscountRedemption.discount))
            .where(
                DiscountRedemption.order_id == order.id,
                DiscountRedemption.status == "active"
            )
        )
        redemptions = redemptions_res.scalars().all()

        new_item_res = await self.db.execute(select(MenuItem).where(MenuItem.id == new_menu_item_id))
        new_item = new_item_res.scalar_one_or_none()

        for r in redemptions:
            disc = r.discount
            if not disc:
                continue

            # Check applicability to replacement
            is_applicable = False
            if disc.applies_to == "all":
                is_applicable = True
            elif disc.applies_to == "items" and disc.target_ids:
                target_strs = [str(t) for t in disc.target_ids]
                is_applicable = any(tid == str(new_menu_item_id) or tid.startswith(f"{new_menu_item_id}::") for tid in target_strs)
            elif disc.applies_to == "category" and disc.target_ids and new_item:
                is_applicable = str(new_item.category_id) in [str(t) for t in disc.target_ids]

            if not is_applicable:
                # Restore discount usage!
                r.status = "restored"
                if r.customer_identifier:
                    await self.db.execute(
                        update(CustomerDiscountCode)
                        .where(
                            CustomerDiscountCode.shop_id == r.shop_id,
                            CustomerDiscountCode.discount_id == r.discount_id,
                            CustomerDiscountCode.customer_identifier == r.customer_identifier
                        )
                        .values(is_redeemed=False, redeemed_at=None)
                    )
            else:
                # Keep active and transfer to replacement
                r.menu_item_id = new_menu_item_id



