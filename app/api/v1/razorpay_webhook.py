import hmac
import hashlib
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Request, HTTPException, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.database.session import get_db
from app.models.order import Order
from app.core.config import get_settings

router = APIRouter(prefix="/webhooks/razorpay", tags=["Webhooks"])

async def process_settlement_async(settlement_id: str, payment_id: str | None, status: str, db: AsyncSession):
    """Background task to fetch settlement details and update orders."""
    settings = get_settings()
    
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        return
        
    try:
        if payment_id:
            # If it's a transfer.settled event, we have the source payment_id
            # Update the specific order that matches this payment_id
            await db.execute(
                update(Order)
                .where(Order.payment_session_id == payment_id)
                .values(
                    settlement_status=status,
                    settled_at=datetime.now(timezone.utc),
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
        
        status = "settled"
        
        if settlement_id:
            background_tasks.add_task(process_settlement_async, settlement_id, payment_id, status, db)
            
            # Since process_settlement_async runs in the background and only updates settlement_id,
            # we can directly extract the transfer ID if it's a transfer event.
            if event == "transfer.settled" and payment_id:
                transfer_id = entity.get("id")
                
                async def update_transfer_id(db_session, t_id, p_id):
                    await db_session.execute(
                        update(Order)
                        .where(Order.payment_session_id == p_id)
                        .values(razorpay_transfer_id=t_id)
                    )
                    await db_session.commit()
                
                background_tasks.add_task(update_transfer_id, db, transfer_id, payment_id)
        
    return {"status": "ok"}
