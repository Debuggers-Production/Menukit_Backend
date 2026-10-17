import hmac
import hashlib
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Request, HTTPException, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.database.session import get_db, async_session_factory
from app.models.order import Order
from app.core.config import get_settings

router = APIRouter(prefix="/webhooks/razorpay", tags=["Webhooks"])

async def process_settlement_async(settlement_id: str, payment_id: str | None, status: str, settled_at_unix: int | None = None):
    """Background task to fetch settlement details and update orders."""
    settings = get_settings()
    
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        return
        
    try:
        if payment_id:
            # If it's a transfer.settled event, we have the source payment_id
            # Update the specific order that matches this payment_id
            async with async_session_factory() as db:
                await db.execute(
                    update(Order)
                    .where(Order.payment_session_id == payment_id)
                    .values(
                        settlement_status=status,
                        settled_at=datetime.fromtimestamp(settled_at_unix, timezone.utc) if settled_at_unix else datetime.now(timezone.utc),
                        razorpay_settlement_id=settlement_id
                    )
                )
                await db.commit()
            print(f"DEBUG: Updated order with payment {payment_id} to {status} for settlement {settlement_id}")
        else:
            # For settlement.processed on main account, we could fetch /settlements/{id}/recon
            # But Razorpay Python SDK or API might require special permissions.
            # For this integration, transfer.settled covers all split orders.
            print(f"DEBUG: Received main account settlement {settlement_id} with status {status}")
            
    except Exception as e:
        print(f"Error processing settlement webhook: {e}")

@router.post("")
async def razorpay_webhook(
    request: Request, 
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """Handle incoming Razorpay webhooks for settlements."""
    settings = get_settings()
    webhook_secret = settings.RAZORPAY_WEBHOOK_SECRET
    
    if not webhook_secret:
        print("Warning: RAZORPAY_WEBHOOK_SECRET is not set, skipping verification")
    
    body_bytes = await request.body()
    body_str = body_bytes.decode('utf-8')
    
    signature = request.headers.get("X-Razorpay-Signature")
    
    if webhook_secret and signature:
        expected_signature = hmac.new(
            key=webhook_secret.encode('utf-8'),
            msg=body_bytes,
            digestmod=hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(expected_signature, signature):
            raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        payload = json.loads(body_str)
        print(f"Razorpay Webhook Payload: {json.dumps(payload, indent=2)}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
        
    event = payload.get("event")
    
    if event in ["settlement.processed", "transfer.settled"]:
        entity = payload.get("payload", {}).get("settlement" if event == "settlement.processed" else "transfer", {}).get("entity", {})
        
        settlement_id = entity.get("id") if event == "settlement.processed" else entity.get("settlement_id")
        payment_id = entity.get("source") if event == "transfer.settled" else None
        
        unix_time = entity.get("processed_at") or entity.get("created_at")
        
        if event == "transfer.settled" and settlement_id:
            recipient_account = entity.get("recipient")
            if recipient_account:
                import requests
                from requests.auth import HTTPBasicAuth
                settings = get_settings()
                url = f"https://api.razorpay.com/v1/settlements/{settlement_id}"
                resp = requests.get(
                    url, 
                    headers={"X-Razorpay-Account": recipient_account},
                    auth=HTTPBasicAuth(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
                )
                if resp.status_code == 200:
                    unix_time = resp.json().get("created_at") or unix_time
        
        status = "settled"
        
        if settlement_id:
            background_tasks.add_task(process_settlement_async, settlement_id, payment_id, status, unix_time)
            
            # Since process_settlement_async runs in the background and only updates settlement_id,
            # we can directly extract the transfer ID if it's a transfer event.
            if event == "transfer.settled" and payment_id:
                transfer_id = entity.get("id")
                
                async def update_transfer_id(t_id, p_id):
                    from app.database.session import async_session_factory
                    async with async_session_factory() as db_session:
                        await db_session.execute(
                            update(Order)
                            .where(Order.payment_session_id == p_id)
                            .values(razorpay_transfer_id=t_id)
                        )
                        await db_session.commit()
                
                background_tasks.add_task(update_transfer_id, transfer_id, payment_id)

    elif event == "refund.processed":
        refund_entity = payload.get("payload", {}).get("refund", {}).get("entity", {})
        payment_id = refund_entity.get("payment_id")
        refund_id = refund_entity.get("id")
        
        if payment_id and refund_id:
            async def process_refund_async(p_id, r_id):
                from app.database.session import async_session_factory
                async with async_session_factory() as db_session:
                    result = await db_session.execute(
                        select(Order).where(Order.payment_session_id == p_id)
                    )
                    order = result.scalar_one_or_none()
                    
                    if order:
                        order.payment_status = "refunded"
                        order.refund_id = r_id
                        await db_session.commit()
                        print(f"DEBUG: Webhook processed refund {r_id} for order {order.id}")
                        print(f"[SMS NOTIFICATION TO CUSTOMER {order.customer_phone}]: Your amount of ₹{order.total_amount} was refunded successfully by Menukit.")
            
            background_tasks.add_task(process_refund_async, payment_id, refund_id)

    elif event == "subscription.charged":
        sub_entity = payload.get("payload", {}).get("subscription", {}).get("entity", {})
        pay_entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
        sub_id = sub_entity.get("id")
        pay_id = pay_entity.get("id")
        amount = (pay_entity.get("amount") or 0) / 100.0

        if sub_id:
            async def process_sub_charged_async(s_id, p_id, amt):
                from app.database.session import async_session_factory
                from app.models.subscription import Subscription, PaymentTransaction
                from app.models.shop import Shop
                from app.models.user import User
                from app.services.invoice_service import InvoiceService
                from app.services.email_service import EmailService
                from datetime import timedelta

                async with async_session_factory() as db_session:
                    sub_stmt = select(Subscription).where(Subscription.razorpay_subscription_id == s_id)
                    res = await db_session.execute(sub_stmt)
                    sub = res.scalar_one_or_none()
                    if not sub:
                        return

                    cycle = getattr(sub, "billing_cycle", "monthly") or "monthly"
                    duration_days = 365 if cycle == "yearly" else 30
                    now = datetime.now(timezone.utc)
                    existing_end = sub.current_period_end
                    if existing_end and existing_end.tzinfo is None:
                        existing_end = existing_end.replace(tzinfo=timezone.utc)
                    base_dt = existing_end if (existing_end and existing_end > now) else now
                    new_period_end = base_dt + timedelta(days=duration_days)

                    # Update module expirations
                    raw_exp = dict(getattr(sub, "module_expirations", {}) or {})
                    for k in raw_exp.keys():
                        raw_exp[k] = new_period_end.isoformat()
                    sub.module_expirations = raw_exp
                    sub.current_period_end = new_period_end
                    sub.is_active = True
                    sub.auto_renew = True

                    # Record transaction
                    new_tx = PaymentTransaction(
                        shop_id=sub.shop_id,
                        razorpay_order_id=s_id,
                        razorpay_payment_id=p_id,
                        amount=amt,
                        currency="INR",
                        status="success",
                        is_all_access=getattr(sub, "is_all_access", False),
                        purchased_modules=sub.active_modules,
                        billing_cycle=cycle,
                        is_autopay=True
                    )
                    db_session.add(new_tx)
                    await db_session.flush()

                    inv_num = InvoiceService.generate_invoice_number(str(new_tx.id))
                    new_tx.invoice_number = inv_num

                    # Sync renewal to other shops owned by user
                    try:
                        shop_res = await db_session.execute(
                            select(Shop, User).join(User, Shop.user_id == User.id).where(Shop.id == sub.shop_id)
                        )
                        shop_user = shop_res.first()
                        if shop_user and shop_user.User:
                            all_user_shops = await db_session.execute(
                                select(Shop).where(Shop.user_id == shop_user.User.id, Shop.id != sub.shop_id)
                            )
                            for o_s in all_user_shops.scalars().all():
                                o_sub_r = await db_session.execute(select(Subscription).where(Subscription.shop_id == o_s.id))
                                o_sub = o_sub_r.scalar_one_or_none()
                                if o_sub:
                                    o_sub.current_period_end = new_period_end
                                    o_sub.module_expirations = raw_exp
                                    o_sub.is_active = True
                                    o_sub.auto_renew = True
                    except Exception as sync_err:
                        print(f"Failed to sync recurring renewal across shops: {sync_err}")

                    await db_session.commit()

                    # Send invoice email
                    try:
                        if shop_user and shop_user.User and shop_user.User.email:
                            inv_data = InvoiceService.build_invoice_data(
                                transaction=new_tx,
                                user_email=shop_user.User.email,
                                shop_name=shop_user.Shop.name,
                                invoice_number=inv_num
                            )
                            email_svc = EmailService()
                            await email_svc.send_subscription_invoice_email(shop_user.User.email, inv_data)
                    except Exception as em_err:
                        print(f"Failed to send recurring invoice email: {em_err}")

            background_tasks.add_task(process_sub_charged_async, sub_id, pay_id, amount)

    elif event in ["subscription.cancelled", "subscription.paused"]:
        sub_entity = payload.get("payload", {}).get("subscription", {}).get("entity", {})
        sub_id = sub_entity.get("id")
        if sub_id:
            async def process_sub_cancelled_async(s_id):
                from app.database.session import async_session_factory
                from app.models.subscription import Subscription
                async with async_session_factory() as db_session:
                    stmt = select(Subscription).where(Subscription.razorpay_subscription_id == s_id)
                    res = await db_session.execute(stmt)
                    sub = res.scalar_one_or_none()
                    if sub:
                        sub.auto_renew = False
                        await db_session.commit()

            background_tasks.add_task(process_sub_cancelled_async, sub_id)

    return {"status": "ok"}
