import os
import logging
from fastapi import APIRouter, Request, Response, Query, HTTPException
from app.core.config import get_settings

# Ensure logs directory exists
os.makedirs("logs", exist_ok=True)

logger = logging.getLogger("whatsapp_webhook")
logger.setLevel(logging.INFO)

if not logger.handlers:
    file_handler = logging.FileHandler("logs/whatsapp_webhook.log", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s"))
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s"))
    logger.addHandler(stream_handler)

router = APIRouter(prefix="/whatsapp", tags=["WhatsApp Webhook"])


@router.get("/webhook")
async def verify_whatsapp_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """
    Meta Cloud API Webhook Verification Endpoint.
    Meta sends GET request with hub.mode, hub.verify_token, hub.challenge.
    """
    settings = get_settings()
    expected_verify_token = getattr(settings, "WHATSAPP_VERIFY_TOKEN", "menukit_whatsapp_webhook_token_2026") or "menukit_whatsapp_webhook_token_2026"

    logger.info(f"WhatsApp Webhook Verification Received: mode={hub_mode}, verify_token={hub_verify_token}")
    print(f"🔍 [WhatsApp Webhook Verify] mode={hub_mode}, verify_token={hub_verify_token}")

    if hub_mode == "subscribe" and hub_verify_token == expected_verify_token:
        logger.info("WhatsApp Webhook Verification SUCCESSFUL!")
        print("✔ [WhatsApp Webhook] Verification SUCCESSFUL!")
        return Response(content=hub_challenge, media_type="text/plain", status_code=200)

    logger.warning("WhatsApp Webhook Verification FAILED: Invalid token or mode")
    print("❌ [WhatsApp Webhook] Verification FAILED: Invalid token or mode")
    raise HTTPException(status_code=403, detail="Verification token mismatch")


@router.post("/webhook")
async def handle_whatsapp_webhook(request: Request):
    """
    Meta Cloud API Webhook Event Receiver.
    Logs incoming message statuses (sent, delivered, read, failed) and inbound messages.
    """
    try:
        import json
        body = await request.json()
        formatted_body = json.dumps(body, indent=2)
        logger.info(f"📩 Incoming WhatsApp Webhook Payload:\n{formatted_body}")
        print(f"📩 [WhatsApp Webhook Log]:\n{formatted_body}")

        # Parse Meta WhatsApp Payload structure
        entries = body.get("entry", [])
        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})

                # 1. Process Delivery Statuses (sent, delivered, read, failed)
                statuses = value.get("statuses", [])
                for stat in statuses:
                    msg_id = stat.get("id")
                    recipient_id = stat.get("recipient_id")
                    status_name = stat.get("status")
                    timestamp = stat.get("timestamp")
                    errors = stat.get("errors")

                    log_msg = f"📱 [WhatsApp Message Status] ID: {msg_id} | Recipient: {recipient_id} | Status: {status_name.upper()} | Time: {timestamp}"
                    if errors:
                        log_msg += f" | Errors: {errors}"

                    logger.info(log_msg)
                    print(log_msg)

                # 2. Process Inbound Messages
                messages = value.get("messages", [])
                for msg in messages:
                    sender_id = msg.get("from")
                    msg_type = msg.get("type")
                    msg_id = msg.get("id")
                    
                    content_preview = ""
                    if msg_type == "text":
                        content_preview = msg.get("text", {}).get("body", "")
                    elif msg_type == "interactive":
                        interactive = msg.get("interactive", {})
                        int_type = interactive.get("type")
                        if int_type == "button_reply":
                            content_preview = interactive.get("button_reply", {}).get("title", "")
                        elif int_type == "list_reply":
                            content_preview = interactive.get("list_reply", {}).get("title", "")
                        else:
                            content_preview = f"Interactive: {int_type}"
                    
                    log_msg = f"💬 [WhatsApp Inbound Message] From: {sender_id} | Type: {msg_type} | Content: {content_preview} | ID: {msg_id}"
                    logger.info(log_msg)
                    print(log_msg)

        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error processing WhatsApp webhook: {e}", exc_info=True)
        print("Error processing WhatsApp webhook:", e)
        # Return 200 OK even on error to prevent Meta from retrying continuously
        return {"status": "ok", "error": str(e)}
