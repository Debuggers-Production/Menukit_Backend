from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from app.services.oauth_service import get_jwks

router = APIRouter(prefix="/.well-known", tags=["Well-Known Discovery"])

@router.get("/oauth-authorization-server")
async def oauth_authorization_server(request: Request):
    """OAuth 2.1 Authorization Server Metadata."""
    base_url = str(request.base_url).rstrip("/")
    auth_domain = f"{base_url}/api/v1" # Customize based on exact domain routing

    metadata = {
        "issuer": auth_domain,
        "authorization_endpoint": f"{auth_domain}/oauth/authorize",
        "token_endpoint": f"{auth_domain}/oauth/token",
        "registration_endpoint": f"{auth_domain}/oauth/register",
        "revocation_endpoint": f"{auth_domain}/oauth/revoke",
        "jwks_uri": f"{auth_domain}/.well-known/jwks.json",
        "scopes_supported": [
            "menukit.read",
            "menukit.write",
            "menukit.shop",
            "menukit.menu",
            "menukit.orders",
            "menukit.analytics",
            "menukit.offers"
        ],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_basic", "client_secret_post"],
        "code_challenge_methods_supported": ["S256"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"]
    }
    return JSONResponse(content=metadata)

@router.get("/oauth-protected-resource")
async def oauth_protected_resource(request: Request):
    """OAuth 2.1 Protected Resource Metadata."""
    base_url = str(request.base_url).rstrip("/")
    # Real MCP server URL is typically different, but we provide base.
    mcp_url = f"{base_url}/mcp" # or the external MCP host
    
    metadata = {
        "resource": mcp_url,
        "authorization_servers": [
            f"{base_url}/api/v1"
        ]
    }
    return JSONResponse(content=metadata)

@router.get("/jwks.json")
async def jwks():
    """Returns the JSON Web Key Set containing the public keys used to sign JWTs."""
    return JSONResponse(content=get_jwks())
