import urllib.parse
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.database.session import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.services.oauth_service import OAuthService
from app.core.config import get_settings

router = APIRouter(prefix="/oauth", tags=["OAuth"])
settings = get_settings()

from pydantic import BaseModel
from typing import List

class ClientRegistrationRequest(BaseModel):
    client_name: str
    redirect_uris: List[str]
    scopes: Optional[str] = "menukit.read menukit.write"

@router.post("/register")
async def register_client(
    request: ClientRegistrationRequest,
    db: AsyncSession = Depends(get_db)
):
    """Dynamic Client Registration for AI/MCP clients."""
    scope_list = [s.strip() for s in request.scopes.split(" ") if s.strip()] if request.scopes else ["menukit.read", "menukit.write"]
    
    client = await OAuthService.create_client(db, request.client_name, request.redirect_uris, scope_list)
    return {
        "client_id": client.client_id,
        "client_name": client.client_name,
        "redirect_uris": client.redirect_uris["uris"],
        "scopes": client.scopes["scopes"]
    }

@router.get("/authorize")
async def authorize_get(
    request: Request,
    client_id: str,
    redirect_uri: str,
    response_type: str,
    scope: str,
    code_challenge: str,
    code_challenge_method: str = "S256",
    state: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Standard OAuth Authorize Endpoint (GET).
    Since Menukit uses Bearer tokens (localStorage) rather than cookies for web auth,
    we redirect the user to the frontend authorization screen with these params.
    """
    client = await OAuthService.get_client(db, client_id)
    if not client:
        return JSONResponse(status_code=400, content={"error": "invalid_client"})
        
    if redirect_uri not in client.redirect_uris.get("uris", []):
        return JSONResponse(status_code=400, content={"error": "invalid_redirect_uri"})
        
    # Redirect to the frontend's OAuth consent/login page
    frontend_url = settings.FRONTEND_URL.rstrip("/")
    query_params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": response_type,
        "scope": scope,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
    }
    if state:
        query_params["state"] = state
        
    qs = urllib.parse.urlencode(query_params)
    return RedirectResponse(url=f"{frontend_url}/oauth-consent?{qs}")

@router.post("/authorize")
async def authorize_post(
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    response_type: str = Form(...),
    scope: str = Form(...),
    code_challenge: str = Form(...),
    code_challenge_method: str = Form("S256"),
    state: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    The frontend calls this endpoint with the Bearer token after the user logs in and consents.
    It returns the redirect URL with the authorization code.
    """
    if response_type != "code":
        return JSONResponse(status_code=400, content={"error": "unsupported_response_type"})
        
    client = await OAuthService.get_client(db, client_id)
    if not client:
        return JSONResponse(status_code=400, content={"error": "invalid_client"})
        
    if redirect_uri not in client.redirect_uris.get("uris", []):
        return JSONResponse(status_code=400, content={"error": "invalid_redirect_uri"})
        
    code = await OAuthService.create_authorization_code(
        db=db,
        client_id=client_id,
        user_id=str(user.id),
        redirect_uri=redirect_uri,
        scope=scope,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method
    )
    
    redirect_url = f"{redirect_uri}?code={code}"
    if state:
        redirect_url += f"&state={urllib.parse.quote(state)}"
        
    # Return the URL so the frontend can window.location.href to it
    return {"redirect_url": redirect_url}

@router.post("/token")
async def token_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """OAuth 2.1 Token Endpoint."""
    form_data = await request.form()
    grant_type = form_data.get("grant_type")
    client_id = form_data.get("client_id")
    
    if grant_type == "authorization_code":
        code = form_data.get("code")
        redirect_uri = form_data.get("redirect_uri")
        code_verifier = form_data.get("code_verifier")
        
        if not all([client_id, code, redirect_uri, code_verifier]):
            return JSONResponse(status_code=400, content={"error": "invalid_request"})
            
        access_token, refresh_token, err_or_meta = await OAuthService.exchange_code_for_tokens(
            db, client_id, code, redirect_uri, code_verifier
        )
        if err_or_meta and "error" in err_or_meta:
            return JSONResponse(status_code=400, content=err_or_meta)
            
        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": err_or_meta.get("expires_in", 3600),
            "refresh_token": refresh_token,
            "scope": err_or_meta.get("scope")
        }
        
    elif grant_type == "refresh_token":
        refresh_token_val = form_data.get("refresh_token")
        
        if not all([client_id, refresh_token_val]):
            return JSONResponse(status_code=400, content={"error": "invalid_request"})
            
        access_token, new_refresh_token, err = await OAuthService.rotate_refresh_token(
            db, client_id, refresh_token_val
        )
        
        if err:
            return JSONResponse(status_code=400, content=err)
            
        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": err.get("expires_in", 3600),
            "refresh_token": new_refresh_token,
            "scope": err.get("scope")
        }
        
    else:
        return JSONResponse(status_code=400, content={"error": "unsupported_grant_type"})

@router.post("/revoke")
async def revoke_token(
    token: str = Form(...),
    token_type_hint: Optional[str] = Form(None),
    client_id: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    """Revoke a refresh token."""
    from sqlalchemy import select, delete
    from app.services.oauth_service import hash_token
    from app.models.oauth import OAuthRefreshToken
    
    hashed = hash_token(token)
    stmt = delete(OAuthRefreshToken).where(
        OAuthRefreshToken.token_hash == hashed,
        OAuthRefreshToken.client_id == client_id
    )
    await db.execute(stmt)
    await db.commit()
    
    return {}
