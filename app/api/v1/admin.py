"""Admin API endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.core.deps import get_current_admin
from app.services.shop_service import ShopService
from app.services.analytics_service import AnalyticsService
from app.models.user import User

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/stats")
async def get_platform_stats(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get platform-wide statistics."""
    service = AnalyticsService(db)
    return await service.get_platform_stats()


@router.get("/restaurants")
async def get_all_restaurants(
    page: int = 1,
    page_size: int = 20,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get paginated list of all restaurants."""
    service = ShopService(db)
    result = await service.get_all_shops(page, page_size)
    
    # Format response
    from app.api.v1.shops import _shop_to_response
    items = [_shop_to_response(shop).model_dump() for shop in result["items"]]
    result["items"] = items
    
    return result


@router.put("/restaurants/{shop_id}/toggle")
async def toggle_restaurant_status(
    shop_id: str,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Enable or disable a restaurant."""
    import uuid
    service = ShopService(db)
    shop = await service.toggle_shop(uuid.UUID(shop_id))
    
    from app.api.v1.shops import _shop_to_response
    return _shop_to_response(shop)

@router.get("/customers")
async def get_all_customers(
    page: int = 1,
    page_size: int = 20,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get paginated list of all customers across the platform."""
    from sqlalchemy import select, func
    from app.models.customer import Customer
    from app.models.membership import CustomerRetailerMembership
    from app.models.shop import Shop
    
    offset = (page - 1) * page_size
    query = select(Customer).order_by(Customer.created_at.desc()).offset(offset).limit(page_size)
    result = await db.execute(query)
    customers = result.scalars().all()
    
    # Fetch shop names for these customers
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
            
    count_query = select(func.count(Customer.id))
    total = await db.execute(count_query)
    total_count = total.scalar() or 0
    
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
        "total": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": (total_count + page_size - 1) // page_size
    }

@router.get("/searches")
async def get_all_searches(
    page: int = 1,
    page_size: int = 50,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get paginated list of all search queries."""
    from sqlalchemy import select, func
    from app.models.analytics import SearchHistory
    
    offset = (page - 1) * page_size
    query = select(SearchHistory).order_by(SearchHistory.searched_at.desc()).offset(offset).limit(page_size)
    result = await db.execute(query)
    searches = result.scalars().all()
    
    count_query = select(func.count(SearchHistory.id))
    total = await db.execute(count_query)
    total_count = total.scalar() or 0
    
    return {
        "items": [{"id": str(s.id), "term": s.search_term, "shop_id": str(s.shop_id) if s.shop_id else None, "created_at": s.searched_at.isoformat() if s.searched_at else None} for s in searches],
        "total": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": (total_count + page_size - 1) // page_size
    }

@router.get("/restaurants/{shop_id}")
async def get_restaurant_details(
    shop_id: str,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get details for a specific restaurant."""
    import uuid
    from app.core.exceptions import NotFoundException
    
    service = ShopService(db)
    shop = await service.get_shop_by_id(uuid.UUID(shop_id))
    if not shop:
        raise NotFoundException("Restaurant not found")
        
    from app.api.v1.shops import _shop_to_response
    return _shop_to_response(shop)

@router.get("/restaurants/{shop_id}/dashboard")
async def get_restaurant_dashboard(
    shop_id: str,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get dashboard stats for a specific restaurant."""
    import uuid
    from app.core.exceptions import NotFoundException
    
    shop_service = ShopService(db)
    shop = await shop_service.get_shop_by_id(uuid.UUID(shop_id))
    if not shop:
        raise NotFoundException("Restaurant not found")
        
    analytics_service = AnalyticsService(db)
    overview = await analytics_service.get_overview(shop.user_id)
    daily_scans = await analytics_service.get_daily_scans(shop.user_id)
    
    # Also get total unique customers specifically for this shop
    from sqlalchemy import select, func
    from app.models.membership import CustomerRetailerMembership
    
    customers_res = await db.execute(
        select(func.count(CustomerRetailerMembership.customer_id))
        .where(CustomerRetailerMembership.shop_id == uuid.UUID(shop_id))
    )
    total_customers = customers_res.scalar() or 0
    overview["total_customers"] = total_customers
    
    return {
        "overview": overview,
        "daily_scans": daily_scans
    }

@router.get("/restaurants/{shop_id}/customers")
async def get_restaurant_customers(
    shop_id: str,
    page: int = 1,
    page_size: int = 50,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get customers who interacted with a specific restaurant."""
    import uuid
    from sqlalchemy import select, func
    from app.models.customer import Customer
    from app.models.membership import CustomerRetailerMembership
    
    shop_uuid = uuid.UUID(shop_id)
    offset = (page - 1) * page_size
    
    # Get customers who have memberships for this shop
    query = (
        select(Customer)
        .join(CustomerRetailerMembership, CustomerRetailerMembership.customer_id == Customer.id)
        .where(CustomerRetailerMembership.shop_id == shop_uuid)
        .order_by(Customer.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(query)
    customers = result.scalars().all()
    
    # Count distinct customers
    count_query = (
        select(func.count(Customer.id))
        .join(CustomerRetailerMembership, CustomerRetailerMembership.customer_id == Customer.id)
        .where(CustomerRetailerMembership.shop_id == shop_uuid)
    )
    total = await db.execute(count_query)
    total_count = total.scalar() or 0
    
    return {
        "items": [{"id": str(c.id), "name": c.name, "mobile_number": c.mobile_number, "created_at": c.created_at.isoformat() if c.created_at else None} for c in customers],
        "total": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": (total_count + page_size - 1) // page_size
    }
