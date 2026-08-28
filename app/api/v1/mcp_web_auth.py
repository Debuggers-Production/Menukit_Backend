"""MCP Web-based Authentication Endpoints."""

import logging
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.database.redis import get_redis
from app.services.otp_service import OTPService
from app.services.email_service import EmailService
from app.services.auth_service import AuthService
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/mcp", tags=["MCP Web Authentication"])

class MCPOTPRequest(BaseModel):
    email: EmailStr

class MCPOTPVerify(BaseModel):
    email: EmailStr
    code: str
    session_id: str

class MCPBindSessionRequest(BaseModel):
    session_id: str
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None


@router.get("/login")
async def redirect_to_frontend_mcp_auth(session_id: Optional[str] = None):
    """Redirect to the frontend web application for MCP authorization."""
    sid = session_id or uuid.uuid4().hex
    frontend_auth_url = f"{settings.FRONTEND_URL}/mcp-auth?session_id={sid}"
    return RedirectResponse(url=frontend_auth_url)


@router.post("/bind-session")
async def bind_mcp_session(
    data: MCPBindSessionRequest,
    request: Request,
    redis=Depends(get_redis)
):
    """Bind an authenticated user's access token to an MCP session_id."""
    token = data.access_token
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]

    if not token:
        raise HTTPException(status_code=401, detail="Authentication token required.")

    session_key = f"mcp_session:{data.session_id}"
    
    # Store token in Redis valid for 7 days (604800 seconds)
    import json
    payload = {
        "access_token": token,
        "refresh_token": data.refresh_token
    }
    await redis.setex(session_key, 604800, json.dumps(payload))
    return {"status": "success", "message": "MCP Session bound successfully."}


@router.post("/request-otp")
async def request_mcp_otp(data: MCPOTPRequest, redis=Depends(get_redis)):
    """Request OTP for MCP Web Login."""
    clean_email = data.email.strip().lower()
    otp_service = OTPService(redis)
    code = await otp_service.create_otp(clean_email)
    
    if not code:
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")
        
    logger.info(f"🔑 [ChatGPT / MCP Login OTP] Email: {clean_email} | OTP Code: {code}")
    print(f"\n\033[96m==================================================\033[0m")
    print(f"\033[96m🤖 ChatGPT / MCP Login OTP Requested\033[0m")
    print(f"\033[96m📧 Email: \033[1m{clean_email}\033[0m")
    print(f"\033[92m🔑 OTP Code: \033[1m{code}\033[0m")
    print(f"\033[96m==================================================\n\033[0m")
        
    if getattr(settings, "ALLOW_TEST_EMAIL", False) and clean_email == getattr(settings, "TEST_EMAIL", "").strip().lower():
        return {"message": "Test OTP sent"}

    email_service = EmailService()
    sent = await email_service.send_otp_email(clean_email, code)
    if not sent:
        raise HTTPException(status_code=500, detail="Failed to send OTP email.")
        
    return {"message": "Verification code sent to email."}


@router.post("/verify-otp")
async def verify_mcp_otp(
    data: MCPOTPVerify,
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """Verify OTP for MCP Web Login and associate JWT token with session_id in Redis."""
    clean_email = data.email.strip().lower()
    otp_service = OTPService(redis)
    is_valid = await otp_service.verify_otp(clean_email, data.code)
    
    if not is_valid:
        raise HTTPException(status_code=400, detail="Invalid or expired verification code.")
        
    auth_service = AuthService(db)
    user = await auth_service.get_or_create_user(clean_email)
    
    user_agent = request.headers.get("user-agent", "")
    ip_address = request.client.host if request.client else None
    
    tokens = await auth_service.create_session(
        user=user,
        device_info=user_agent[:200] if user_agent else "MCP Web Auth",
        browser_info="MCP Web",
        ip_address=ip_address
    )
    await db.commit()
    
    session_key = f"mcp_session:{data.session_id}"
    access_token = tokens["access_token"]
    
    # Store in Redis with expiration (7 days = 604800 seconds)
    await redis.setex(session_key, 604800, access_token)
    
    return {"status": "success", "access_token": access_token, "message": "Authenticated successfully"}
