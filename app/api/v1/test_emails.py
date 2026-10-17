"""Test routes for triggering and previewing all Menukit email templates."""

import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Query, HTTPException, Body, Depends
from pydantic import BaseModel, EmailStr, Field

from app.services.email_service import email_service
from app.core.config import get_settings

settings = get_settings()


def check_non_production():
    """Ensure testing routes cannot be executed in production environment."""
    if getattr(settings, "is_production", False):
        raise HTTPException(status_code=404, detail="Not Found")


router = APIRouter(
    prefix="/test-emails",
    tags=["Email Template Testing"],
    dependencies=[Depends(check_non_production)]
)


class SendTestEmailRequest(BaseModel):
    """Payload to trigger an email template test."""
    email: EmailStr = Field(..., description="Target email address to send the test email to", example="sivarajan@example.com")
    template: str = Field(
        default="new_order",
        description="Template to test: auth_otp, deletion_otp, employee_invite, new_order, subscription_expiring, subscription_expired, weekend_digest, or all",
        example="new_order"
    )
    shop_name: Optional[str] = Field(default="Siva Hotel", description="Custom shop name for the template", example="Siva Hotel")
    customer_name: Optional[str] = Field(default="Siva", description="Customer name for applicable templates", example="Siva")
    force_smtp: bool = Field(default=True, description="Force actual delivery via SMTP directly to the inbox")


AVAILABLE_TEMPLATES = [
    {
        "key": "auth_otp",
        "name": "Login Verification OTP",
        "description": "6-digit OTP email sent during sign-up or login verification.",
        "sample_fields": {"email": "user@example.com", "otp_code": "489215"}
    },
    {
        "key": "deletion_otp",
        "name": "Security Deletion OTP",
        "description": "High-priority security alert with OTP code required before deleting categories/menu items.",
        "sample_fields": {"email": "user@example.com", "otp_code": "824109", "target": "Categories & Menu Items"}
    },
    {
        "key": "employee_invite",
        "name": "Employee Staff Invitation",
        "description": "Invitation email with secure verification link for staff / cashiers to join a restaurant team.",
        "sample_fields": {"email": "user@example.com", "shop_name": "Siva Hotel", "verify_link": "https://..."}
    },
    {
        "key": "new_order",
        "name": "New Order Alert for Admin",
        "description": "Instant notification when an order is placed, with channel (Dine-in/Delivery), item table, and grand total.",
        "sample_fields": {"email": "admin@example.com", "shop_name": "Siva Hotel", "order_ref": "ORD-7294", "total_amount": 350.00}
    },
    {
        "key": "subscription_expiring",
        "name": "Subscription Expiring Notice (3 Days Left)",
        "description": "Warning email sent 3 days before smart menu / add-on modules expire with a renewal link.",
        "sample_fields": {"email": "owner@example.com", "shop_name": "Siva Hotel", "min_days": 3, "modules": ["SmartMenu Full Plan"]}
    },
    {
        "key": "subscription_expired",
        "name": "Subscription Expired Alert",
        "description": "Urgent alert sent when modules have expired (sent every 2 days) with a reactivation link.",
        "sample_fields": {"email": "owner@example.com", "shop_name": "Siva Hotel", "modules": ["SmartMenu Full Plan"]}
    },
    {
        "key": "weekend_digest",
        "name": "Weekend Total Customers Summary Digest",
        "description": "Weekly weekend performance digest reporting total registered customer count, new customers, orders, and revenue.",
        "sample_fields": {"email": "owner@example.com", "shop_name": "Siva Hotel", "total_customers": 1420, "revenue_this_week": 48250.00}
    },
    {
        "key": "all",
        "name": "Send All Templates",
        "description": "Dispatches all 7 email templates sequentially to test all designs at once.",
        "sample_fields": {"email": "your_email@example.com"}
    }
]


@router.get("/templates")
async def list_available_templates():
    """List all available email templates with descriptions and sample field documentation."""
    return {
        "status": "success",
        "total_templates": len(AVAILABLE_TEMPLATES),
        "templates": AVAILABLE_TEMPLATES,
        "smtp_backend": settings.EMAIL_BACKEND,
        "smtp_from": settings.SMTP_FROM_EMAIL,
    }


async def _dispatch_template(
    template_key: str,
    email: str,
    shop_name: str = "Siva Hotel",
    customer_name: str = "Siva",
    force_smtp: bool = True
) -> Dict[str, Any]:
    """Internal helper to dispatch a specific template with realistic dummy data."""
    t_key = template_key.lower().strip()

    if t_key == "auth_otp":
        otp = "739201"
        res = await email_service.send_otp_email(email=email, otp_code=otp, force_smtp=force_smtp)
        return {"template": "auth_otp", "success": res, "subject": f"Your SmartMenu QR Login Code: {otp}"}

    elif t_key == "deletion_otp":
        otp = "842915"
        res = await email_service.send_deletion_otp_email(
            email=email, otp_code=otp, target="Categories & Menu Items", force_smtp=force_smtp
        )
        return {"template": "deletion_otp", "success": res, "subject": f"⚠️ Security Alert: OTP to Confirm Deletion ({otp})"}

    elif t_key == "employee_invite":
        token = str(uuid.uuid4())
        res = await email_service.send_employee_invite_email(
            email=email, token=token, shop_name=shop_name, force_smtp=force_smtp
        )
        return {"template": "employee_invite", "success": res, "subject": f"You're invited to join {shop_name} on SmartMenu"}

    elif t_key == "new_order":
        items = [
            {"name": "Paneer Butter Masala", "quantity": 2, "price": 140.0, "variant_info": "Spicy • Full"},
            {"name": "Butter Naan", "quantity": 4, "price": 35.0, "variant_info": None},
            {"name": "Fresh Lime Soda", "quantity": 2, "price": 40.0, "variant_info": "Sweet"},
        ]
        res = await email_service.send_new_order_admin_email(
            email=email,
            shop_name=shop_name,
            order_ref="ORD-9418",
            customer_name=customer_name,
            customer_phone="9876543210",
            order_type="dine_in",
            table_number="Table #4",
            delivery_address=None,
            payment_method="upi",
            payment_status="paid",
            total_amount=500.0,
            items=items,
            created_at_str=datetime.now(timezone.utc).strftime("%d %b %Y, %I:%M %p UTC"),
            force_smtp=force_smtp
        )
        return {"template": "new_order", "success": res, "subject": f"🛒 New Order ORD-9418 (Dine-in (Table #4)) - ₹500.00 | {shop_name}"}

    elif t_key == "subscription_expiring":
        res = await email_service.send_subscription_expiring_email(
            email=email,
            shop_name=shop_name,
            min_days=3,
            expiring_modules=["SmartMenu Full Plan", "WhatsApp Marketing Module"],
            force_smtp=force_smtp
        )
        return {"template": "subscription_expiring", "success": res, "subject": f"Notice: Your SmartMenu Modules are Expiring Soon ({shop_name})"}

    elif t_key == "subscription_expired":
        res = await email_service.send_subscription_expired_email(
            email=email,
            shop_name=shop_name,
            expired_modules=["SmartMenu Full Plan", "Digital Chalkboard Module"],
            force_smtp=force_smtp
        )
        return {"template": "subscription_expired", "success": res, "subject": "Action Required: Your SmartMenu Subscription Has Expired"}

    elif t_key == "weekend_digest":
        res = await email_service.send_weekend_customer_summary_email(
            email=email,
            shop_name=shop_name,
            total_customers=1420,
            new_customers_this_week=86,
            orders_this_week=342,
            revenue_this_week=54890.0,
            weekend_label="Weekly Customer & Performance Digest",
            force_smtp=force_smtp
        )
        return {"template": "weekend_digest", "success": res, "subject": f"Weekend Digest: 1,420 Total Customers for {shop_name}"}

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown template '{template_key}'. Available: auth_otp, deletion_otp, employee_invite, new_order, subscription_expiring, subscription_expired, weekend_digest, all"
        )


@router.post("/send")
async def send_test_email(payload: SendTestEmailRequest):
    """Main route to trigger any email template test or all templates together."""
    t_key = payload.template.lower().strip()

    if t_key == "all":
        results = []
        keys = ["auth_otp", "deletion_otp", "employee_invite", "new_order", "subscription_expiring", "subscription_expired", "weekend_digest"]
        for k in keys:
            r = await _dispatch_template(
                template_key=k,
                email=str(payload.email),
                shop_name=payload.shop_name or "Siva Hotel",
                customer_name=payload.customer_name or "Siva",
                force_smtp=payload.force_smtp
            )
            results.append(r)
        return {
            "status": "success",
            "message": f"All {len(results)} email templates dispatched to {payload.email}",
            "recipient": payload.email,
            "dispatched_templates": results
        }

    res = await _dispatch_template(
        template_key=t_key,
        email=str(payload.email),
        shop_name=payload.shop_name or "Siva Hotel",
        customer_name=payload.customer_name or "Siva",
        force_smtp=payload.force_smtp
    )
    return {
        "status": "success" if res.get("success") else "failed",
        "message": f"Template '{t_key}' sent to {payload.email}",
        "details": res
    }


# ── Individual One-Click Test Routes ──────────────────────────────────────────

@router.post("/auth-otp")
async def test_auth_otp(email: EmailStr = Query(..., description="Recipient email address")):
    """Trigger the Login/Authentication OTP Code email."""
    res = await _dispatch_template("auth_otp", str(email), force_smtp=True)
    return {"status": "success", "template": "auth_otp", "recipient": email, "result": res}


@router.post("/deletion-otp")
async def test_deletion_otp(email: EmailStr = Query(..., description="Recipient email address")):
    """Trigger the Security Deletion OTP alert email."""
    res = await _dispatch_template("deletion_otp", str(email), force_smtp=True)
    return {"status": "success", "template": "deletion_otp", "recipient": email, "result": res}


@router.post("/employee-invite")
async def test_employee_invite(
    email: EmailStr = Query(..., description="Recipient email address"),
    shop_name: str = Query(default="Siva Hotel", description="Restaurant / Shop Name")
):
    """Trigger the Employee Team Invitation email."""
    res = await _dispatch_template("employee_invite", str(email), shop_name=shop_name, force_smtp=True)
    return {"status": "success", "template": "employee_invite", "recipient": email, "result": res}


@router.post("/new-order")
async def test_new_order(
    email: EmailStr = Query(..., description="Recipient email address"),
    shop_name: str = Query(default="Siva Hotel", description="Restaurant / Shop Name"),
    customer_name: str = Query(default="Siva", description="Customer Name")
):
    """Trigger the Immediate New Order notification email for admins."""
    res = await _dispatch_template("new_order", str(email), shop_name=shop_name, customer_name=customer_name, force_smtp=True)
    return {"status": "success", "template": "new_order", "recipient": email, "result": res}


@router.post("/subscription-expiring")
async def test_subscription_expiring(
    email: EmailStr = Query(..., description="Recipient email address"),
    shop_name: str = Query(default="Siva Hotel", description="Restaurant / Shop Name")
):
    """Trigger the 3-day Subscription Expiring warning email."""
    res = await _dispatch_template("subscription_expiring", str(email), shop_name=shop_name, force_smtp=True)
    return {"status": "success", "template": "subscription_expiring", "recipient": email, "result": res}


@router.post("/subscription-expired")
async def test_subscription_expired(
    email: EmailStr = Query(..., description="Recipient email address"),
    shop_name: str = Query(default="Siva Hotel", description="Restaurant / Shop Name")
):
    """Trigger the Subscription Expired alert email."""
    res = await _dispatch_template("subscription_expired", str(email), shop_name=shop_name, force_smtp=True)
    return {"status": "success", "template": "subscription_expired", "recipient": email, "result": res}


@router.post("/weekend-digest")
async def test_weekend_digest(
    email: EmailStr = Query(..., description="Recipient email address"),
    shop_name: str = Query(default="Siva Hotel", description="Restaurant / Shop Name")
):
    """Trigger the Weekend Total Customers Count and Performance Summary digest email."""
    res = await _dispatch_template("weekend_digest", str(email), shop_name=shop_name, force_smtp=True)
    return {"status": "success", "template": "weekend_digest", "recipient": email, "result": res}


@router.post("/send-all")
async def test_send_all(
    email: EmailStr = Query(..., description="Recipient email address"),
    shop_name: str = Query(default="Siva Hotel", description="Restaurant / Shop Name")
):
    """Trigger ALL 7 email templates sequentially to the target email address."""
    results = []
    keys = ["auth_otp", "deletion_otp", "employee_invite", "new_order", "subscription_expiring", "subscription_expired", "weekend_digest"]
    for k in keys:
        r = await _dispatch_template(template_key=k, email=str(email), shop_name=shop_name, force_smtp=True)
        results.append(r)
    return {
        "status": "success",
        "message": f"Successfully sent all {len(results)} email templates to {email}",
        "recipient": email,
        "results": results
    }


# ── Quick Browser GET Trigger Route ──────────────────────────────────────────

@router.get("/quick-send")
async def quick_send_email_get(
    email: EmailStr = Query(..., description="Target email address"),
    template: str = Query(default="new_order", description="Template key (auth_otp, deletion_otp, employee_invite, new_order, subscription_expiring, subscription_expired, weekend_digest, all)"),
    shop_name: str = Query(default="Siva Hotel", description="Shop name")
):
    """Quick GET endpoint for testing email delivery directly via browser URL bar."""
    if template.lower().strip() == "all":
        return await test_send_all(email=email, shop_name=shop_name)

    res = await _dispatch_template(template_key=template, email=str(email), shop_name=shop_name, force_smtp=True)
    return {
        "status": "success" if res.get("success") else "failed",
        "message": f"Template '{template}' dispatched to {email}",
        "details": res
    }
