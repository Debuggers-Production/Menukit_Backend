"""Admin API endpoints for platform management."""

import uuid
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, Query, Body
from sqlalchemy import select, func, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.session import get_db
from app.core.deps import get_current_admin
from app.core.exceptions import NotFoundException, BadRequestException
from app.models.user import User
from app.models.shop import Shop
from app.models.customer import Customer
from app.models.membership import CustomerRetailerMembership
from app.models.broadcast import BroadcastCampaign
from app.models.subscription import Subscription, PaymentTransaction
from app.models.menu_catalog import MenuCatalog
from app.models.category import Category
from app.models.menu_item import MenuItem
from app.models.order import Order
from app.models.contest import Contest
from app.models.analytics import QRScan, MenuView, SearchHistory
from app.services.shop_service import ShopService
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/admin", tags=["Admin"])


class UpdateRoleRequest(BaseModel):
    role: str


# ==============================================================================
# PLATFORM SUMMARY / STATS
# ==============================================================================

@router.get("/summary")
@router.get("/stats")
async def get_admin_summary(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Aggregated platform overview metrics."""
    # User counts
    users_count = (await db.execute(select(func.count(User.id)))).scalar() or 0
    
    # Shop counts
    total_shops = (await db.execute(select(func.count(Shop.id)))).scalar() or 0
    active_shops = (await db.execute(select(func.count(Shop.id)).where(Shop.is_active == True))).scalar() or 0
    
    # Menu & Items counts
    total_items = (await db.execute(select(func.count(MenuItem.id)))).scalar() or 0
    total_categories = (await db.execute(select(func.count(Category.id)))).scalar() or 0
    total_catalogs = (await db.execute(select(func.count(MenuCatalog.id)))).scalar() or 0
    
    # Campaigns count
    total_campaigns = (await db.execute(select(func.count(BroadcastCampaign.id)))).scalar() or 0
    sent_campaigns = (
        await db.execute(select(func.count(BroadcastCampaign.id)).where(BroadcastCampaign.status == "SENT"))
    ).scalar() or 0
    
    # Customers count
    total_customers = (await db.execute(select(func.count(Customer.id)))).scalar() or 0
    
    # Orders count & volume
    total_orders = (await db.execute(select(func.count(Order.id)))).scalar() or 0
    total_revenue = (
        await db.execute(select(func.coalesce(func.sum(Order.total_amount), 0.0)).where(Order.order_status != "cancelled"))
    ).scalar() or 0.0

    # Subscriptions
    active_subs = (
        await db.execute(select(func.count(Subscription.id)).where(Subscription.is_active == True))
    ).scalar() or 0
    paid_subs = (
        await db.execute(
            select(func.count(Subscription.id)).where(
                Subscription.is_active == True,
                Subscription.is_trial == False
            )
        )
    ).scalar() or 0

    return {
        "total_users": users_count,
        "total_shops": total_shops,
        "active_shops": active_shops,
        "inactive_shops": total_shops - active_shops,
        "total_menu_items": total_items,
        "total_categories": total_categories,
        "total_catalogs": total_catalogs,
        "total_campaigns": total_campaigns,
        "sent_campaigns": sent_campaigns,
        "total_customers": total_customers,
        "total_orders": total_orders,
        "total_revenue": round(float(total_revenue), 2),
        "active_subscriptions": active_subs,
        "paid_subscriptions": paid_subs,
    }


# ==============================================================================
# USERS MANAGEMENT
# ==============================================================================

@router.get("/users")
async def get_all_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = Query("", description="Search by email"),
    role: str = Query("", description="Filter by role"),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get paginated list of all users with owned shops and subscription status."""
    query = select(User).options(selectinload(User.shops))
    
    if search.strip():
        term = f"%{search.strip()}%"
        query = query.where(User.email.ilike(term))
        
    if role.strip():
        query = query.where(User.role == role.strip())

    # Count query
    count_query = select(func.count(User.id))
    if search.strip():
        count_query = count_query.where(User.email.ilike(f"%{search.strip()}%"))
    if role.strip():
        count_query = count_query.where(User.role == role.strip())
        
    total = (await db.execute(count_query)).scalar() or 0
    
    # Pagination
    offset = (page - 1) * page_size
    query = query.order_by(User.created_at.desc()).offset(offset).limit(page_size)
    result = await db.execute(query)
    users = result.scalars().all()

    # Pre-fetch subscription status for owned shops
    all_shop_ids = [shop.id for user in users for shop in (user.shops or [])]
    shop_sub_map = {}
    if all_shop_ids:
        sub_query = select(Subscription).where(Subscription.shop_id.in_(all_shop_ids))
        sub_res = await db.execute(sub_query)
        for s in sub_res.scalars().all():
            shop_sub_map[s.shop_id] = s

    items = []
    for u in users:
        shops_list = []
        has_active_sub = False
        for s in (u.shops or []):
            sub = shop_sub_map.get(s.id)
            is_active_sub = sub.is_active if sub else False
            if is_active_sub:
                has_active_sub = True
            shops_list.append({
                "id": str(s.id),
                "name": s.name,
                "slug": s.slug,
                "city": s.city,
                "is_active": s.is_active,
                "plan": "Pro" if (sub and sub.is_all_access) else ("Trial" if (sub and sub.is_trial) else "Free")
            })

        items.append({
            "id": str(u.id),
            "email": u.email,
            "role": u.role,
            "is_active": u.is_active,
            "last_login": u.last_login.isoformat() if u.last_login else None,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "shops_count": len(shops_list),
            "shops": shops_list,
            "has_active_subscription": has_active_sub,
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.put("/users/{user_id}/toggle")
async def toggle_user_active(
    user_id: str,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Toggle user active / suspended status."""
    u_uuid = uuid.UUID(user_id)
    user = (await db.execute(select(User).where(User.id == u_uuid))).scalar_one_or_none()
    if not user:
        raise NotFoundException("User not found")
        
    user.is_active = not user.is_active
    await db.commit()
    await db.refresh(user)
    return {"id": str(user.id), "email": user.email, "is_active": user.is_active}


@router.put("/users/{user_id}/role")
async def update_user_role(
    user_id: str,
    req: UpdateRoleRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update user role (e.g. owner or admin)."""
    if req.role not in ["owner", "admin"]:
        raise BadRequestException("Role must be 'owner' or 'admin'")
        
    u_uuid = uuid.UUID(user_id)
    user = (await db.execute(select(User).where(User.id == u_uuid))).scalar_one_or_none()
    if not user:
        raise NotFoundException("User not found")
        
    user.role = req.role
    await db.commit()
    await db.refresh(user)
    return {"id": str(user.id), "email": user.email, "role": user.role}


# ==============================================================================
# SHOPS MANAGEMENT & DEEP INSPECTION
# ==============================================================================

@router.get("/shops")
@router.get("/restaurants")
async def get_all_shops_admin(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = Query("", description="Search by name, slug, city, or owner email"),
    status: str = Query("all", description="all, active, inactive"),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get paginated list of all shops with owner info, counts, and subscription status."""
    query = (
        select(Shop)
        .join(User, Shop.user_id == User.id)
        .options(selectinload(Shop.user), selectinload(Shop.subscription))
    )

    if search.strip():
        term = f"%{search.strip()}%"
        query = query.where(
            or_(
                Shop.name.ilike(term),
                Shop.slug.ilike(term),
                Shop.city.ilike(term),
                User.email.ilike(term)
            )
        )

    if status == "active":
        query = query.where(Shop.is_active == True)
    elif status == "inactive":
        query = query.where(Shop.is_active == False)

    # Count
    count_query = select(func.count(Shop.id)).join(User, Shop.user_id == User.id)
    if search.strip():
        term = f"%{search.strip()}%"
        count_query = count_query.where(
            or_(
                Shop.name.ilike(term),
                Shop.slug.ilike(term),
                Shop.city.ilike(term),
                User.email.ilike(term)
            )
        )
    if status == "active":
        count_query = count_query.where(Shop.is_active == True)
    elif status == "inactive":
        count_query = count_query.where(Shop.is_active == False)

    total = (await db.execute(count_query)).scalar() or 0

    offset = (page - 1) * page_size
    query = query.order_by(Shop.created_at.desc()).offset(offset).limit(page_size)
    shops = (await db.execute(query)).scalars().all()

    shop_ids = [s.id for s in shops]
    catalog_ids = [s.menu_catalog_id for s in shops if s.menu_catalog_id]

    # Pre-aggregate counts for the page
    categories_counts = {}
    items_counts = {}
    if catalog_ids:
        # Category counts per catalog
        cat_res = await db.execute(
            select(Category.menu_catalog_id, func.count(Category.id))
            .where(Category.menu_catalog_id.in_(catalog_ids))
            .group_by(Category.menu_catalog_id)
        )
        for cat_id, cnt in cat_res:
            categories_counts[cat_id] = cnt

        # Items counts per catalog
        item_res = await db.execute(
            select(MenuItem.menu_catalog_id, func.count(MenuItem.id))
            .where(MenuItem.menu_catalog_id.in_(catalog_ids))
            .group_by(MenuItem.menu_catalog_id)
        )
        for cat_id, cnt in item_res:
            items_counts[cat_id] = cnt

    # WhatsApp Campaigns count per shop
    campaign_counts = {}
    if shop_ids:
        camp_res = await db.execute(
            select(BroadcastCampaign.shop_id, func.count(BroadcastCampaign.id))
            .where(BroadcastCampaign.shop_id.in_(shop_ids))
            .group_by(BroadcastCampaign.shop_id)
        )
        for sid, cnt in camp_res:
            campaign_counts[sid] = cnt

    # Customer counts per shop
    customer_counts = {}
    if shop_ids:
        cust_res = await db.execute(
            select(CustomerRetailerMembership.shop_id, func.count(CustomerRetailerMembership.customer_id))
            .where(CustomerRetailerMembership.shop_id.in_(shop_ids))
            .group_by(CustomerRetailerMembership.shop_id)
        )
        for sid, cnt in cust_res:
            customer_counts[sid] = cnt

    # Orders count per shop
    order_counts = {}
    if shop_ids:
        ord_res = await db.execute(
            select(Order.shop_id, func.count(Order.id))
            .where(Order.shop_id.in_(shop_ids))
            .group_by(Order.shop_id)
        )
        for sid, cnt in ord_res:
            order_counts[sid] = cnt

    items = []
    for s in shops:
        sub = s.subscription
        plan_name = "Free"
        if sub and sub.is_active:
            if sub.is_all_access:
                plan_name = "Pro All-Access"
            elif sub.is_trial:
                plan_name = "Free Trial"
            else:
                plan_name = "Custom Modules"
        elif sub and not sub.is_active:
            plan_name = "Expired"

        items.append({
            "id": str(s.id),
            "name": s.name,
            "slug": s.slug,
            "logo_url": s.logo_url,
            "banner_url": s.banner_url,
            "phone": s.phone,
            "whatsapp": s.whatsapp,
            "city": s.city,
            "area": s.area,
            "category": s.category,
            "cuisine": s.cuisine,
            "is_active": s.is_active,
            "broadcast_credits": s.broadcast_credits,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "owner": {
                "id": str(s.user.id) if s.user else None,
                "email": s.user.email if s.user else "Unknown",
                "role": s.user.role if s.user else "owner",
            },
            "counts": {
                "total_menus": 1 if s.menu_catalog_id else 0,
                "total_categories": categories_counts.get(s.menu_catalog_id, 0),
                "total_items": items_counts.get(s.menu_catalog_id, 0),
                "total_campaigns": campaign_counts.get(s.id, 0),
                "total_customers": customer_counts.get(s.id, 0),
                "total_orders": order_counts.get(s.id, 0),
            },
            "subscription": {
                "is_active": sub.is_active if sub else False,
                "is_trial": sub.is_trial if sub else False,
                "is_all_access": sub.is_all_access if sub else False,
                "current_period_end": sub.current_period_end.isoformat() if (sub and sub.current_period_end) else None,
                "plan_name": plan_name,
            }
        })

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.put("/shops/{shop_id}/toggle")
@router.put("/restaurants/{shop_id}/toggle")
async def toggle_shop_active(
    shop_id: str,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Enable or disable a restaurant."""
    s_uuid = uuid.UUID(shop_id)
    shop = (await db.execute(select(Shop).where(Shop.id == s_uuid))).scalar_one_or_none()
    if not shop:
        raise NotFoundException("Restaurant not found")
        
    shop.is_active = not shop.is_active
    await db.commit()
    await db.refresh(shop)
    return {"id": str(shop.id), "name": shop.name, "is_active": shop.is_active}


@router.get("/shops/{shop_id}/detail")
async def get_shop_full_details(
    shop_id: str,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Comprehensive shop inspector view:
    - Shop core info & owner info
    - Menus / catalogs & total count
    - Categories & item counts
    - Menu items list
    - WhatsApp Campaigns history & status
    - Subscription details & payment transactions
    - Customer list with contact info & spending stats
    - Performance metrics (scans, orders, revenue)
    """
    s_uuid = uuid.UUID(shop_id)
    
    # 1. Fetch Shop with User and Subscription
    query = (
        select(Shop)
        .where(Shop.id == s_uuid)
        .options(
            selectinload(Shop.user),
            selectinload(Shop.subscription),
            selectinload(Shop.settings),
            selectinload(Shop.theme),
        )
    )
    shop = (await db.execute(query)).scalar_one_or_none()
    if not shop:
        raise NotFoundException("Restaurant not found")

    # 2. Catalogs, Categories & Menu Items
    catalogs_list = []
    categories_list = []
    menu_items_list = []

    # Get catalogs owned by user or linked to shop
    cat_query = select(MenuCatalog).where(
        or_(MenuCatalog.id == shop.menu_catalog_id, MenuCatalog.user_id == shop.user_id)
    )
    catalogs = (await db.execute(cat_query)).scalars().all()
    catalog_ids = [c.id for c in catalogs]

    if catalog_ids:
        # Fetch categories
        cats_res = await db.execute(
            select(Category)
            .where(Category.menu_catalog_id.in_(catalog_ids))
            .order_by(Category.display_order.asc())
        )
        categories = cats_res.scalars().all()

        # Fetch menu items
        items_res = await db.execute(
            select(MenuItem)
            .where(MenuItem.menu_catalog_id.in_(catalog_ids))
            .order_by(MenuItem.display_order.asc(), MenuItem.name.asc())
        )
        menu_items = items_res.scalars().all()

        # Build category item counts & map
        cat_item_counts = {}
        for item in menu_items:
            cat_item_counts[item.category_id] = cat_item_counts.get(item.category_id, 0) + 1

        cat_name_map = {c.id: c.name for c in categories}

        for cat in categories:
            categories_list.append({
                "id": str(cat.id),
                "catalog_id": str(cat.menu_catalog_id),
                "name": cat.name,
                "image_url": cat.image_url,
                "display_order": cat.display_order,
                "is_active": cat.is_active,
                "items_count": cat_item_counts.get(cat.id, 0),
            })

        for item in menu_items:
            img_url = None
            if hasattr(item, "images") and item.images:
                img_url = item.images[0].image_url
            elif hasattr(item, "image_url"):
                img_url = getattr(item, "image_url", None)

            menu_items_list.append({
                "id": str(item.id),
                "catalog_id": str(item.menu_catalog_id),
                "category_id": str(item.category_id),
                "category_name": cat_name_map.get(item.category_id, "Uncategorized"),
                "name": item.name,
                "price": float(item.price),
                "description": item.description,
                "image_url": img_url,
                "is_available": item.is_available,
                "is_veg": "veg" in (getattr(item, "food_types", None) or ["veg"]),
            })

        for catlog in catalogs:
            catalogs_list.append({
                "id": str(catlog.id),
                "name": catlog.name,
                "is_current": (catlog.id == shop.menu_catalog_id),
                "created_at": catlog.created_at.isoformat() if catlog.created_at else None,
                "categories_count": len([c for c in categories if c.menu_catalog_id == catlog.id]),
                "items_count": len([i for i in menu_items if i.menu_catalog_id == catlog.id]),
            })

    # 3. WhatsApp Campaigns
    campaigns_res = await db.execute(
        select(BroadcastCampaign)
        .where(BroadcastCampaign.shop_id == s_uuid)
        .order_by(BroadcastCampaign.created_at.desc())
    )
    campaigns = campaigns_res.scalars().all()
    campaigns_list = [
        {
            "id": str(c.id),
            "title": c.title,
            "message": c.message,
            "image_url": c.image_url,
            "target_audience": c.target_audience,
            "status": c.status,
            "total_recipients": c.total_recipients,
            "sent_count": c.sent_count,
            "failed_count": c.failed_count,
            "scheduled_at": c.scheduled_at.isoformat() if c.scheduled_at else None,
            "sent_at": c.sent_at.isoformat() if c.sent_at else None,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "error_details": c.error_details,
        }
        for c in campaigns
    ]

    # 4. Subscription & Payment Transactions
    sub = shop.subscription
    plan_name = "Free Tier"
    days_remaining = None
    if sub:
        if sub.current_period_end:
            now = datetime.now(timezone.utc)
            end = sub.current_period_end
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            delta = (end - now).days
            days_remaining = max(0, delta)

        if sub.is_active:
            if sub.is_all_access:
                plan_name = "Pro All-Access"
            elif sub.is_trial:
                plan_name = "Free Trial"
            else:
                plan_name = "Custom Modules"
        else:
            plan_name = "Expired"

    subscription_info = {
        "id": str(sub.id) if sub else None,
        "is_active": sub.is_active if sub else False,
        "is_trial": sub.is_trial if sub else False,
        "is_all_access": sub.is_all_access if sub else False,
        "active_modules": sub.active_modules if sub else [],
        "module_expirations": sub.module_expirations if sub else {},
        "current_period_end": sub.current_period_end.isoformat() if (sub and sub.current_period_end) else None,
        "razorpay_subscription_id": sub.razorpay_subscription_id if sub else None,
        "plan_name": plan_name,
        "days_remaining": days_remaining,
    }

    # Payment transactions
    payments_res = await db.execute(
        select(PaymentTransaction)
        .where(PaymentTransaction.shop_id == s_uuid)
        .order_by(PaymentTransaction.created_at.desc())
    )
    payments = payments_res.scalars().all()
    payments_list = [
        {
            "id": str(p.id),
            "amount": float(p.amount),
            "currency": p.currency,
            "status": p.status,
            "billing_cycle": p.billing_cycle,
            "invoice_number": p.invoice_number,
            "razorpay_order_id": p.razorpay_order_id,
            "razorpay_payment_id": p.razorpay_payment_id,
            "is_all_access": p.is_all_access,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in payments
    ]

    # 5. Customers associated with this shop
    customers_res = await db.execute(
        select(Customer, CustomerRetailerMembership.created_at, CustomerRetailerMembership.is_retailer_added)
        .join(CustomerRetailerMembership, CustomerRetailerMembership.customer_id == Customer.id)
        .where(CustomerRetailerMembership.shop_id == s_uuid)
        .order_by(CustomerRetailerMembership.created_at.desc())
    )
    cust_rows = customers_res.all()

    # Precompute customer order totals for this shop
    cust_phones = [c.mobile_number for c, _, _ in cust_rows if c.mobile_number]
    cust_stats = {}
    if cust_phones:
        stats_query = (
            select(
                Order.customer_phone,
                func.count(Order.id),
                func.coalesce(func.sum(Order.total_amount), 0.0),
                func.max(Order.created_at)
            )
            .where(Order.shop_id == s_uuid, Order.customer_phone.in_(cust_phones))
            .group_by(Order.customer_phone)
        )
        stats_res = await db.execute(stats_query)
        for phone, cnt, total_spent, last_order in stats_res:
            cust_stats[phone] = {
                "orders_count": cnt,
                "total_spent": round(float(total_spent), 2),
                "last_order": last_order.isoformat() if last_order else None
            }

    customers_list = [
        {
            "id": str(c.id),
            "name": c.name or "Guest Customer",
            "mobile_number": c.mobile_number,
            "joined_at": joined_at.isoformat() if joined_at else None,
            "is_retailer_added": is_added,
            "orders_count": cust_stats.get(c.mobile_number, {}).get("orders_count", 0),
            "total_spent": cust_stats.get(c.mobile_number, {}).get("total_spent", 0.0),
            "last_order_at": cust_stats.get(c.mobile_number, {}).get("last_order", None),
        }
        for c, joined_at, is_added in cust_rows
    ]

    # 6. Analytics & Performance overview
    total_scans = (
        await db.execute(select(func.count(QRScan.id)).where(QRScan.shop_id == s_uuid))
    ).scalar() or 0

    total_views = (
        await db.execute(select(func.count(MenuView.id)).where(MenuView.shop_id == s_uuid))
    ).scalar() or 0

    orders_count = (
        await db.execute(select(func.count(Order.id)).where(Order.shop_id == s_uuid))
    ).scalar() or 0

    orders_revenue = (
        await db.execute(
            select(func.coalesce(func.sum(Order.total_amount), 0.0))
            .where(Order.shop_id == s_uuid, Order.order_status != "cancelled")
        )
    ).scalar() or 0.0

    contests_count = (
        await db.execute(select(func.count(Contest.id)).where(Contest.shop_id == s_uuid))
    ).scalar() or 0

    return {
        "shop": {
            "id": str(shop.id),
            "name": shop.name,
            "slug": shop.slug,
            "description": shop.description,
            "welcome_message": shop.welcome_message,
            "logo_url": shop.logo_url,
            "banner_url": shop.banner_url,
            "phone": shop.phone,
            "whatsapp": shop.whatsapp,
            "address": shop.address,
            "category": shop.category,
            "cuisine": shop.cuisine,
            "city": shop.city,
            "area": shop.area,
            "opening_time": shop.opening_time,
            "closing_time": shop.closing_time,
            "is_active": shop.is_active,
            "broadcast_credits": shop.broadcast_credits,
            "created_at": shop.created_at.isoformat() if shop.created_at else None,
        },
        "owner": {
            "id": str(shop.user.id) if shop.user else None,
            "email": shop.user.email if shop.user else "Unknown",
            "role": shop.user.role if shop.user else "owner",
            "is_active": shop.user.is_active if shop.user else True,
            "last_login": shop.user.last_login.isoformat() if (shop.user and shop.user.last_login) else None,
            "created_at": shop.user.created_at.isoformat() if (shop.user and shop.user.created_at) else None,
        },
        "metrics": {
            "total_menus": len(catalogs_list),
            "total_categories": len(categories_list),
            "total_items": len(menu_items_list),
            "total_campaigns": len(campaigns_list),
            "total_customers": len(customers_list),
            "total_scans": total_scans,
            "total_views": total_views,
            "total_orders": orders_count,
            "total_revenue": round(float(orders_revenue), 2),
            "total_contests": contests_count,
            "broadcast_credits": shop.broadcast_credits,
        },
        "catalogs": catalogs_list,
        "categories": categories_list,
        "menu_items": menu_items_list,
        "campaigns": campaigns_list,
        "subscription": subscription_info,
        "payment_transactions": payments_list,
        "customers": customers_list,
    }


# ==============================================================================
# BACKWARD-COMPATIBLE ALIASES & SEARCHES
# ==============================================================================

@router.get("/restaurants/{shop_id}")
async def get_restaurant_details_compat(
    shop_id: str,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get single restaurant details."""
    s_uuid = uuid.UUID(shop_id)
    service = ShopService(db)
    shop = await service.get_shop_by_id(s_uuid)
    if not shop:
        raise NotFoundException("Restaurant not found")
        
    from app.api.v1.shops import _shop_to_response
    return _shop_to_response(shop)


@router.get("/restaurants/{shop_id}/dashboard")
async def get_restaurant_dashboard_compat(
    shop_id: str,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get dashboard stats for a specific restaurant."""
    s_uuid = uuid.UUID(shop_id)
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_id(s_uuid)
    if not shop:
        raise NotFoundException("Restaurant not found")
        
    analytics_service = AnalyticsService(db)
    overview = await analytics_service.get_overview(shop.user_id)
    daily_scans = await analytics_service.get_daily_scans(shop.user_id)
    
    customers_res = await db.execute(
        select(func.count(CustomerRetailerMembership.customer_id))
        .where(CustomerRetailerMembership.shop_id == s_uuid)
    )
    total_customers = customers_res.scalar() or 0
    overview["total_customers"] = total_customers
    
    return {
        "overview": overview,
        "daily_scans": daily_scans
    }


@router.get("/restaurants/{shop_id}/customers")
async def get_restaurant_customers_compat(
    shop_id: str,
    page: int = 1,
    page_size: int = 50,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get customers who interacted with a specific restaurant."""
    s_uuid = uuid.UUID(shop_id)
    offset = (page - 1) * page_size
    
    query = (
        select(Customer)
        .join(CustomerRetailerMembership, CustomerRetailerMembership.customer_id == Customer.id)
        .where(CustomerRetailerMembership.shop_id == s_uuid)
        .order_by(Customer.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(query)
    customers = result.scalars().all()
    
    count_query = (
        select(func.count(Customer.id))
        .join(CustomerRetailerMembership, CustomerRetailerMembership.customer_id == Customer.id)
        .where(CustomerRetailerMembership.shop_id == s_uuid)
    )
    total = (await db.execute(count_query)).scalar() or 0
    
    return {
        "items": [
            {
                "id": str(c.id),
                "name": c.name,
                "mobile_number": c.mobile_number,
                "created_at": c.created_at.isoformat() if c.created_at else None
            }
            for c in customers
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size
    }


@router.get("/customers")
async def get_all_customers_admin(
    page: int = 1,
    page_size: int = 20,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get paginated list of all customers across the platform."""
    offset = (page - 1) * page_size
    query = select(Customer).order_by(Customer.created_at.desc()).offset(offset).limit(page_size)
    result = await db.execute(query)
    customers = result.scalars().all()
    
    customer_ids = [c.id for c in customers]
    shop_names = {}
    if customer_ids:
        shop_query = (
            select(CustomerRetailerMembership.customer_id, Shop.name)
            .join(Shop, Shop.id == CustomerRetailerMembership.shop_id)
            .where(CustomerRetailerMembership.customer_id.in_(customer_ids))
        )
        shop_res = await db.execute(shop_query)
        for cid, sname in shop_res:
            if cid not in shop_names:
                shop_names[cid] = []
            shop_names[cid].append(sname)
            
    total = (await db.execute(select(func.count(Customer.id)))).scalar() or 0
    
    return {
        "items": [
            {
                "id": str(c.id), 
                "name": c.name or "Anonymous",
                "mobile_number": c.mobile_number, 
                "shop_names": ", ".join(shop_names.get(c.id, [])) or "None",
                "created_at": c.created_at.isoformat() if c.created_at else None
            } 
            for c in customers
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size
    }


@router.get("/searches")
async def get_all_searches_admin(
    page: int = 1,
    page_size: int = 50,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get paginated list of all search queries."""
    offset = (page - 1) * page_size
    query = select(SearchHistory).order_by(SearchHistory.searched_at.desc()).offset(offset).limit(page_size)
    result = await db.execute(query)
    searches = result.scalars().all()
    
    total = (await db.execute(select(func.count(SearchHistory.id)))).scalar() or 0
    
    return {
        "items": [
            {
                "id": str(s.id),
                "term": s.search_term,
                "shop_id": str(s.shop_id) if s.shop_id else None,
                "created_at": s.searched_at.isoformat() if s.searched_at else None
            }
            for s in searches
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size
    }
