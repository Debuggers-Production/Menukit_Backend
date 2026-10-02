"""Shop management API endpoints."""

import uuid
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.database.session import get_db
from app.core.deps import get_current_user, require_permission
from app.schemas.shop import (
    ShopCreate, ShopUpdate, ShopResponse,
    ShopSettingsUpdate, ShopSettingsResponse,
    ThemeSettingsUpdate, ThemeSettingsResponse,
    RazorpayBankAccountUpdateRequest,
    RazorpayLinkedAccountCreateRequest,
)
from app.schemas.chalkboard import ChalkboardUpdate, ChalkboardResponse
from app.services.shop_service import ShopService
from app.models.user import User

import hmac
import hashlib
import logging
from datetime import datetime, timezone
from sqlalchemy import select
from app.models.subscription import Subscription, PaymentTransaction
from app.core.config import get_settings, is_phone_exempt

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/shops", tags=["shops"])

# Initialize Razorpay Client
razorpay_client = None
if settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET:
    try:
        import razorpay
        razorpay_client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    except ImportError:
        razorpay_client = None


@router.post("/additional-shop-order")
async def create_additional_shop_order(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create Razorpay order for ₹50 additional shop add-on fee (or return free if 1st shop/exempt)."""
    service = ShopService(db)
    shops_info = await service.get_shops_for_user(user.id)
    owned_count = len(shops_info.get("owned", []))
    is_exempt = is_phone_exempt(user.phone)
    
    # First shop or exempt phone number is free
    if owned_count == 0 or is_exempt:
        return {
            "required": False,
            "amount": 0,
            "currency": "INR",
            "message": "Free shop creation included"
        }
        
    amount_inr = 50.0
    amount_paise = 5000
    
    # Check mock payment mode
    if getattr(settings, "MOCK_PAYMENT_MODE", False) or not razorpay_client:
        mock_order_id = f"order_mock_add_shop_{uuid.uuid4().hex[:12]}"
        return {
            "required": True,
            "mock_mode": True,
            "order_id": mock_order_id,
            "amount": amount_inr,
            "currency": "INR",
            "key_id": "rzp_mock_key"
        }
        
    try:
        receipt_id = f"add_shop_{str(user.id)[:8]}_{int(datetime.now().timestamp())}"
        order_payload = {
            "amount": amount_paise,
            "currency": "INR",
            "receipt": receipt_id,
            "notes": {
                "user_id": str(user.id),
                "type": "additional_shop_addon",
                "price": "50"
            }
        }
        razorpay_order = razorpay_client.order.create(data=order_payload)
        return {
            "required": True,
            "mock_mode": False,
            "order_id": razorpay_order["id"],
            "amount": amount_inr,
            "currency": "INR",
            "key_id": settings.RAZORPAY_KEY_ID
        }
    except Exception as e:
        logger.error(f"Failed to create Razorpay order for additional shop: {e}")
        mock_order_id = f"order_mock_add_shop_{uuid.uuid4().hex[:12]}"
        return {
            "required": True,
            "mock_mode": True,
            "order_id": mock_order_id,
            "amount": amount_inr,
            "currency": "INR",
            "key_id": "rzp_mock_key"
        }


@router.post("", response_model=ShopResponse)
async def create_shop(
    data: ShopCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new shop profile (with ₹50 add-on fee for additional shops)."""
    if not user.phone or not user.phone_verified:
        raise HTTPException(
            status_code=403,
            detail="Authentication phone verification required. Please link and verify your mobile number before creating a shop."
        )

    service = ShopService(db)
    shops_info = await service.get_shops_for_user(user.id)
    owned_count = len(shops_info.get("owned", []))
    is_exempt = is_phone_exempt(user.phone)

    # If user already owns >= 1 shop and is not exempt, require & verify payment
    if owned_count >= 1 and not is_exempt:
        has_payment = bool(data.razorpay_payment_id or data.razorpay_order_id)
        is_mock_payment = (
            getattr(settings, "MOCK_PAYMENT_MODE", False) or 
            str(data.razorpay_payment_id or "").startswith("pay_mock_") or
            str(data.razorpay_order_id or "").startswith("order_mock_")
        )
        
        if not has_payment and not is_mock_payment:
            raise HTTPException(
                status_code=402,
                detail="Additional shop requires a ₹50/month add-on fee. Please complete payment."
            )
            
        if not is_mock_payment and settings.RAZORPAY_KEY_SECRET and data.razorpay_signature:
            generated_sig = hmac.new(
                settings.RAZORPAY_KEY_SECRET.encode(),
                f"{data.razorpay_order_id}|{data.razorpay_payment_id}".encode(),
                hashlib.sha256
            ).hexdigest()
            if generated_sig != data.razorpay_signature:
                raise HTTPException(status_code=400, detail="Invalid payment signature")

    shop_dict = data.model_dump(exclude_none=True)
    order_id = shop_dict.pop("razorpay_order_id", None)
    payment_id = shop_dict.pop("razorpay_payment_id", None)
    signature = shop_dict.pop("razorpay_signature", None)

    shop = await service.create_shop(user.id, shop_dict)

    # 1. Inherit/clone primary shop's subscription to the new shop
    try:
        if owned_count > 0:
            primary_shop = shops_info["owned"][0]
            sub_stmt = select(Subscription).where(Subscription.shop_id == primary_shop.id)
            sub_res = await db.execute(sub_stmt)
            primary_sub = sub_res.scalar_one_or_none()
            if primary_sub:
                new_sub = Subscription(
                    shop_id=shop.id,
                    is_active=primary_sub.is_active,
                    is_all_access=primary_sub.is_all_access,
                    is_trial=primary_sub.is_trial,
                    active_modules=primary_sub.active_modules,
                    module_expirations=primary_sub.module_expirations,
                    current_period_end=primary_sub.current_period_end
                )
                db.add(new_sub)
    except Exception as e:
        logger.warning(f"Failed to clone subscription to new shop: {e}")

    # 2. Record PaymentTransaction if payment was provided
    if order_id or payment_id:
        try:
            tx = PaymentTransaction(
                shop_id=shop.id,
                razorpay_order_id=order_id or f"order_addon_{uuid.uuid4().hex[:10]}",
                razorpay_payment_id=payment_id or f"pay_addon_{uuid.uuid4().hex[:10]}",
                razorpay_signature=signature or "verified",
                amount=50.0,
                currency="INR",
                status="success",
                is_all_access=False,
                purchased_modules=["additional-shop"],
                billing_cycle="monthly"
            )
            db.add(tx)
        except Exception as e:
            logger.warning(f"Failed to record additional shop payment transaction: {e}")

    await db.commit()
    return _shop_to_response(shop)


@router.get("/my-shops")
async def get_my_shops(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all shops the user has access to (owned and employed)."""
    service = ShopService(db)
    shops_info = await service.get_shops_for_user(user.id)
    
    # Format the response
    owned = [_shop_to_response(s).model_dump() for s in shops_info.get("owned", [])]
    employed = []
    for emp in shops_info.get("employed", []):
        if isinstance(emp, dict):
            resp = _shop_to_response(emp["shop"]).model_dump()
            resp["employee_permissions"] = emp.get("permissions", {})
        else:
            resp = _shop_to_response(emp).model_dump()
            resp["employee_permissions"] = getattr(emp, "_employee_permissions", {})
        employed.append(resp)
        
    return {
        "owned": owned,
        "employed": employed
    }


@router.get("/brand/{user_id}/branches")
async def get_brand_branches(
    user_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get all public branches for a given brand (user)."""
    service = ShopService(db)
    try:
        user_uuid = uuid.UUID(user_id)
        shops_info = await service.get_shops_for_user(user_uuid)
        active_owned = [s for s in shops_info["owned"] if s.is_active]
        return [_shop_to_response(s) for s in active_owned]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid brand ID")


@router.get("/me", response_model=ShopResponse)
async def get_my_shop(
    x_shop_id: Optional[str] = Header(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current user's shop with subscription-based feature data filtering."""
    service = ShopService(db)
    
    def _extract_emp(emp_entry):
        if isinstance(emp_entry, dict):
            return emp_entry.get("shop"), emp_entry.get("permissions", {})
        return emp_entry, getattr(emp_entry, "_employee_permissions", {})

    employee_permissions = None
    if x_shop_id:
        shops_info = await service.get_shops_for_user(user.id)
        shop = None
        for s in shops_info.get("owned", []):
            if str(s.id) == x_shop_id:
                shop = s
                break
        if not shop:
            for emp_entry in shops_info.get("employed", []):
                e_shop, e_perm = _extract_emp(emp_entry)
                if e_shop and str(e_shop.id) == x_shop_id:
                    shop = e_shop
                    employee_permissions = e_perm
                    break
        # Fallback if x_shop_id was stale / not found
        if not shop:
            if shops_info.get("owned"):
                shop = shops_info["owned"][0]
            elif shops_info.get("employed"):
                shop, employee_permissions = _extract_emp(shops_info["employed"][0])
    else:
        shop = await service.get_shop_by_user(user.id)
        if not shop:
            shops_info = await service.get_shops_for_user(user.id)
            if shops_info.get("employed"):
                shop, employee_permissions = _extract_emp(shops_info["employed"][0])
        
    if not shop:
        return ShopResponse(
            id="", name="", slug="", is_active=False, created_at=""
        )
        
    response = await format_shop_response_with_subscription_checks(shop, db)
    if employee_permissions is not None:
        response.employee_permissions = employee_permissions
    return response


async def invalidate_shop_cache(shop_id: uuid.UUID):
    """Invalidate Redis public shop cache."""
    try:
        from app.database.redis import get_redis
        r_client = await get_redis()
        await r_client.delete(f"public:shop:{str(shop_id)}")
    except Exception:
        pass


@router.put("/me", response_model=ShopResponse)
async def update_my_shop(
    data: ShopUpdate,
    shop = Depends(require_permission("settings", "write")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the current user's shop."""
    service = ShopService(db)
    shop_updated = await service.update_shop(shop.id, user.id, data.model_dump(exclude_unset=True))
    await db.commit()
    await invalidate_shop_cache(shop.id)
    return await format_shop_response_with_subscription_checks(shop_updated, db)


@router.put("/me/theme", response_model=ThemeSettingsResponse)
async def update_theme(
    data: ThemeSettingsUpdate,
    shop = Depends(require_permission("settings", "write")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update shop theme settings, enforcing subscription check."""
    from app.services.subscription_helper import get_shop_subscription_permissions
    perms = await get_shop_subscription_permissions(shop.id, db)
    if not perms["custom_theme"]:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=403,
            detail="Custom Theme Studio is locked due to expired subscription. Please renew your subscription to save custom themes."
        )
            
    theme = await ShopService(db).update_theme(shop.id, user.id, data.model_dump(exclude_none=True))
    await db.commit()
    await invalidate_shop_cache(shop.id)
    return ThemeSettingsResponse(
        id=str(theme.id),
        theme=theme.theme,
        primary_color=theme.primary_color,
        secondary_color=theme.secondary_color,
        font_family=theme.font_family,
        layout=theme.layout,
        banner_style=theme.banner_style,
        theme_scope=theme.theme_scope,
        discount_card_style=theme.discount_card_style,
        menu_item_style=theme.menu_item_style,
        border_radius=theme.border_radius,
    )


@router.get("/me/chalkboard", response_model=ChalkboardResponse)
async def get_chalkboard(
    shop = Depends(require_permission("chalkboard", "read")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get chalkboard settings for the merchant shop."""
    chalkboard = await ShopService(db).get_chalkboard(shop.id)
    return ChalkboardResponse.model_validate(chalkboard)


@router.put("/me/chalkboard", response_model=ChalkboardResponse)
async def update_chalkboard(
    data: ChalkboardUpdate,
    shop = Depends(require_permission("chalkboard", "write")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update chalkboard settings for the merchant shop."""
    chalkboard = await ShopService(db).update_chalkboard(
        shop.id, user.id, data.model_dump(exclude_unset=True)
    )
    await db.commit()
    await invalidate_shop_cache(shop.id)
    return ChalkboardResponse.model_validate(chalkboard)


@router.put("/me/settings", response_model=ShopSettingsResponse)
async def update_settings(
    data: ShopSettingsUpdate,
    shop = Depends(require_permission("settings", "write")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update shop settings."""
    dumped_data = data.model_dump(exclude_unset=True)

    service = ShopService(db)
    settings = await service.update_settings(shop.id, user.id, dumped_data)
    await db.commit()

    # Invalidate public shop cache
    await invalidate_shop_cache(shop.id)

    return ShopSettingsResponse.model_validate(settings)



@router.patch("/me/razorpay/bank-account")
async def update_razorpay_bank_account(
    data: RazorpayBankAccountUpdateRequest,
    shop = Depends(require_permission("settings", "write")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update Razorpay Route linked account bank details."""
    service = ShopService(db)
    result = await service.update_razorpay_bank_account(user.id, data, shop_id=shop.id)
    await db.commit()
    return result


@router.post("/me/razorpay/linked-account")
async def create_razorpay_linked_account(
    data: RazorpayLinkedAccountCreateRequest,
    shop = Depends(require_permission("settings", "write")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new Razorpay Route linked account with bank details."""
    service = ShopService(db)
    result = await service.create_razorpay_linked_account(user.id, data, shop_id=shop.id)
    await db.commit()
    return result


@router.get("/me/razorpay/status")
async def get_razorpay_account_status(
    shop = Depends(require_permission("settings", "read")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch current Razorpay Route verification status."""
    service = ShopService(db)
    result = await service.get_razorpay_account_status(user.id, shop_id=shop.id)
    await db.commit()
    return result


async def format_shop_response_with_subscription_checks(shop, db: AsyncSession) -> ShopResponse:
    """Convert Shop model to response schema enforcing subscription level feature permissions."""
    from app.services.subscription_helper import get_shop_subscription_permissions
    perms = await get_shop_subscription_permissions(shop.id, db)
    
    theme_resp = None
    if shop.theme:
        if perms["custom_theme"]:
            theme_resp = ThemeSettingsResponse(
                id=str(shop.theme.id),
                theme=shop.theme.theme,
                primary_color=shop.theme.primary_color,
                secondary_color=shop.theme.secondary_color,
                font_family=shop.theme.font_family,
                layout=shop.theme.layout,
                banner_style=shop.theme.banner_style,
                theme_scope=shop.theme.theme_scope,
                discount_card_style=shop.theme.discount_card_style,
                menu_item_style=shop.theme.menu_item_style,
                border_radius=shop.theme.border_radius,
            )
        else:
            # Automatic fallback to DEFAULT theme when custom_theme is locked/expired
            theme_resp = ThemeSettingsResponse(
                id=str(shop.theme.id),
                theme="light",
                primary_color="#f97316",
                secondary_color="#1e293b",
                font_family="Inter",
                layout=getattr(shop.theme, "layout", "standard") or "standard",
                banner_style=getattr(shop.theme, "banner_style", "hero") or "hero",
                theme_scope="public",
                discount_card_style="modern",
                menu_item_style="default",
                border_radius="smooth",
            )

    settings_resp = None
    if shop.settings:
        settings_dict = ShopSettingsResponse.model_validate(shop.settings).model_dump()
        is_bank_verified = bool(shop.settings.bank_account_last4) and shop.settings.razorpay_route_status in ["activated", "active"]
        if not is_bank_verified:
            settings_dict["dinein_enabled"] = False
            settings_dict["takeaway_enabled"] = False
            settings_dict["delivery_enabled"] = False
            settings_dict["online_payments_enabled"] = False
        elif not perms["online_orders"]:
            # Automatic disable takeaway and delivery if online_orders is locked/expired
            settings_dict["allow_takeaway"] = False
            settings_dict["allow_delivery"] = False
            settings_dict["takeaway_enabled"] = False
            settings_dict["delivery_enabled"] = False
        settings_resp = ShopSettingsResponse(**settings_dict)

    chalkboard_resp = None
    if getattr(shop, "chalkboard", None):
        chalkboard_resp = ChalkboardResponse.model_validate(shop.chalkboard)

    return ShopResponse(
        id=str(shop.id),
        user_id=str(shop.user_id) if shop.user_id else None,
        name=shop.name,
        slug=shop.slug,
        description=shop.description,
        welcome_message=shop.welcome_message,
        logo_url=shop.logo_url,
        banner_url=shop.banner_url,
        phone=shop.phone,
        whatsapp=shop.whatsapp,
        address=shop.address,
        category=getattr(shop, "category", None),
        cuisine=getattr(shop, "cuisine", None),
        city=getattr(shop, "city", None),
        area=getattr(shop, "area", None),
        opening_time=shop.opening_time,
        closing_time=shop.closing_time,
        is_active=shop.is_active,
        latitude=shop.latitude,
        longitude=shop.longitude,
        google_review_link=shop.google_review_link,
        review_widget_code=shop.review_widget_code,
        settings=settings_resp,
        theme=theme_resp,
        chalkboard=chalkboard_resp,
        created_at=str(shop.created_at),
    )


def _shop_to_response(shop) -> ShopResponse:
    """Convert Shop model to response schema."""
    theme_resp = None
    if shop.theme:
        theme_resp = ThemeSettingsResponse(
            id=str(shop.theme.id),
            theme=shop.theme.theme,
            primary_color=shop.theme.primary_color,
            secondary_color=shop.theme.secondary_color,
            font_family=shop.theme.font_family,
            layout=shop.theme.layout,
            banner_style=shop.theme.banner_style,
            theme_scope=shop.theme.theme_scope,
            discount_card_style=shop.theme.discount_card_style,
            menu_item_style=shop.theme.menu_item_style,
            border_radius=shop.theme.border_radius,
        )

    settings_resp = None
    if shop.settings:
        settings_resp = ShopSettingsResponse.model_validate(shop.settings)

    chalkboard_resp = None
    if getattr(shop, "chalkboard", None):
        chalkboard_resp = ChalkboardResponse.model_validate(shop.chalkboard)

    return ShopResponse(
        id=str(shop.id),
        user_id=str(shop.user_id) if shop.user_id else None,
        name=shop.name,
        slug=shop.slug,
        description=shop.description,
        welcome_message=shop.welcome_message,
        logo_url=shop.logo_url,
        banner_url=shop.banner_url,
        phone=shop.phone,
        whatsapp=shop.whatsapp,
        address=shop.address,
        category=getattr(shop, "category", None),
        cuisine=getattr(shop, "cuisine", None),
        city=getattr(shop, "city", None),
        area=getattr(shop, "area", None),
        opening_time=shop.opening_time,
        closing_time=shop.closing_time,
        is_active=shop.is_active,
        latitude=shop.latitude,
        longitude=shop.longitude,
        google_review_link=shop.google_review_link,
        review_widget_code=shop.review_widget_code,
        settings=settings_resp,
        theme=theme_resp,
        chalkboard=chalkboard_resp,
        created_at=str(shop.created_at),
    )

