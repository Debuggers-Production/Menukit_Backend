import re

with open("app/services/analytics_service.py", "r") as f:
    content = f.read()

start_marker = "        from sqlalchemy import case"
start_idx = content.find(start_marker)

end_marker = "    async def get_overview_analytics("
end_idx = content.find(end_marker)

new_code = """        from sqlalchemy import case
        import asyncio
        from app.database.session import async_session_factory
        from app.models.analytics import MenuView
        
        # 1. Total Orders, Gross Revenue & Commission in current period
        online_methods = ["online", "upi", "card", "pay_online", "razorpay", "cashfree"]
        is_online_condition = func.lower(func.coalesce(Order.payment_method, "cash")).in_(online_methods)
        
        q_agg = select(
            func.count(Order.id).label("count"),
            func.sum(Order.total_amount).label("gross"),
            func.sum(case((is_online_condition, Order.total_amount * 0.02), else_=0.0)).label("commission")
        ).where(
            Order.shop_id == shop_id,
            Order.created_at >= since,
            Order.created_at <= until,
            Order.order_status.notin_(["rejected", "cancelled"])
        )

        q_prev = select(func.sum(Order.total_amount)).where(
            Order.shop_id == shop_id,
            Order.created_at >= prev_since,
            Order.created_at < prev_until,
            Order.order_status.notin_(["rejected", "cancelled"])
        )

        q_recent = select(Order).where(
            Order.shop_id == shop_id,
            Order.created_at >= since,
            Order.created_at <= until,
            Order.order_status.notin_(["rejected", "cancelled"])
        ).order_by(desc(Order.created_at)).limit(50)

        q_daily = select(
            func.date(Order.created_at).label("date"),
            func.count(Order.id).label("count"),
            func.sum(Order.total_amount).label("sum_amt"),
            func.sum(case((is_online_condition, Order.total_amount * 0.02), else_=0.0)).label("commission")
        ).where(
            Order.shop_id == shop_id,
            Order.created_at >= since,
            Order.created_at <= until,
            Order.order_status.notin_(["rejected", "cancelled"])
        ).group_by(func.date(Order.created_at)).order_by(func.date(Order.created_at))

        q_items = select(
            OrderItem.name,
            func.sum(OrderItem.quantity).label("total_qty"),
            func.sum(OrderItem.price * OrderItem.quantity).label("total_rev")
        ).join(Order, Order.id == OrderItem.order_id).where(
            Order.shop_id == shop_id,
            Order.created_at >= since,
            Order.created_at <= until,
            Order.order_status.notin_(["rejected", "cancelled"])
        ).group_by(OrderItem.name).order_by(desc("total_qty")).limit(15)

        q_cats = select(
            Category.name,
            func.count(func.distinct(MenuView.ip_address)).label("total_qty")
        ).select_from(MenuView).join(Category, Category.id == MenuView.category_id).where(
            MenuView.shop_id == shop_id,
            MenuView.viewed_at >= since,
            MenuView.viewed_at <= until
        ).group_by(Category.name).order_by(desc("total_qty")).limit(10)

        async def fetch_scalar(query):
            async with async_session_factory() as db:
                res = await db.execute(query)
                return res.scalar()
                
        async def fetch_first(query):
            async with async_session_factory() as db:
                res = await db.execute(query)
                return res.first()

        async def fetch_all(query):
            async with async_session_factory() as db:
                res = await db.execute(query)
                return res.all()
                
        async def fetch_scalars_all(query):
            async with async_session_factory() as db:
                res = await db.execute(query)
                return list(res.scalars().all())

        agg_row, prev_revenue, recent_orders, daily_rows, top_items_rows, top_categories_rows = await asyncio.gather(
            fetch_first(q_agg),
            fetch_scalar(q_prev),
            fetch_scalars_all(q_recent),
            fetch_all(q_daily),
            fetch_all(q_items),
            fetch_all(q_cats)
        )

        total_orders_count = agg_row.count or 0 if agg_row else 0
        total_gross = float(agg_row.gross or 0.0) if agg_row else 0.0
        total_commission_paid = float(agg_row.commission or 0.0) if agg_row else 0.0
        total_settled_amount = round(total_gross - total_commission_paid, 2)
        prev_revenue = float(prev_revenue or 0.0)

        # 3. Growth Ratio
        if prev_revenue > 0:
            growth_ratio = round(((total_gross - prev_revenue) / prev_revenue) * 100, 1)
        elif total_gross > 0:
            growth_ratio = 100.0
        else:
            growth_ratio = 0.0

        recent_invoices = []
        for o in recent_orders:
            pm = (o.payment_method or "cash").lower()
            is_online = pm in online_methods
            rate = 0.02 if is_online else 0.0
            comm = float(o.total_amount or 0.0) * rate
            settled = float(o.total_amount or 0.0) - comm

            inv_no = f"INV-{o.created_at.strftime('%Y%m%d')}-{str(o.id)[:6].upper()}"
            recent_invoices.append({
                "order_id": str(o.id),
                "invoice_no": inv_no,
                "payment_id": o.cashfree_order_id or o.payment_session_id or f"PAY-{str(o.id)[:8].upper()}",
                "payment_method": o.payment_method or "cash",
                "customer_name": o.customer_name or "Guest",
                "customer_phone": o.customer_phone or "",
                "total_order_amt": round(float(o.total_amount or 0.0), 2),
                "commission_rate": round(rate * 100, 1),
                "commission_amount": round(comm, 2),
                "settled_amount": round(settled, 2),
                "order_status": o.order_status,
                "created_at": o.created_at.strftime("%b %d, %Y %I:%M %p")
            })

        daily_sales = []
        for row in daily_rows:
            gross = float(row.sum_amt or 0.0)
            comm = float(row.commission or 0.0)
            daily_sales.append({
                "date": str(row.date),
                "orders_count": row.count,
                "gross_revenue": round(gross, 2),
                "commission_amount": round(comm, 2),
                "settled_amount": round(gross - comm, 2)
            })

        top_ordered_items = []
        for row in top_items_rows:
            top_ordered_items.append({
                "name": row.name,
                "total_quantity": int(row.total_qty or 0),
                "total_revenue": round(float(row.total_rev or 0.0), 2)
            })

        highest_revenue_food = top_ordered_items[0] if top_ordered_items else None
        by_quantity = sorted(top_ordered_items, key=lambda x: x["total_quantity"], reverse=True)
        most_ordered_food = by_quantity[0] if by_quantity else None

        top_ordered_categories = []
        for row in top_categories_rows:
            top_ordered_categories.append({
                "name": row.name,
                "total_quantity": int(row.total_qty or 0),
                "total_revenue": 0.0
            })

        return {
            "total_gross_revenue": round(total_gross, 2),
            "total_settled_amount": total_settled_amount,
            "total_commission_paid": round(total_commission_paid, 2),
            "total_orders_count": total_orders_count,
            "highest_revenue_food": highest_revenue_food,
            "most_ordered_food": most_ordered_food,
            "growth_ratio": growth_ratio,
            "top_ordered_items": top_ordered_items,
            "top_ordered_categories": top_ordered_categories,
            "daily_sales": daily_sales,
            "recent_invoices": recent_invoices
        }
"""

if start_idx != -1 and end_idx != -1:
    new_content = content[:start_idx] + new_code + "\n" + content[end_idx:]
    with open("app/services/analytics_service.py", "w") as f:
        f.write(new_content)
    print("Success")
else:
    print("Failed")
