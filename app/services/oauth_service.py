"""OAuth 2.1 Service."""

import hashlib
import base64
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from jose import jwt, jwk
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

from app.models.oauth import OAuthClient, OAuthAuthorizationCode, OAuthRefreshToken
from app.core.config import get_settings

settings = get_settings()

# RSA Key Pair for JWT signing (In production, this should be loaded from env or secure storage)
# For this implementation, we will generate an ephemeral key on startup if one isn't provided.
# A real implementation would persist this.

import os

_private_key = None
_public_key = None
_kid = "menukit-mcp-key-1"

KEY_DIR = os.path.dirname(os.path.abspath(__file__))
PRIV_KEY_FILE = os.path.join(KEY_DIR, "oauth_rsa_private.pem")
PUB_KEY_FILE = os.path.join(KEY_DIR, "oauth_rsa_public.pem")

def get_or_generate_rsa_key():
    global _private_key, _public_key
    if _private_key is None or _public_key is None:
        if os.path.exists(PRIV_KEY_FILE) and os.path.exists(PUB_KEY_FILE):
            with open(PRIV_KEY_FILE, "r") as f:
                _private_key = f.read()
            with open(PUB_KEY_FILE, "r") as f:
                _public_key = f.read()
        else:
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            _private_key = key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            ).decode("utf-8")
            
            pub_key = key.public_key()
            _public_key = pub_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            ).decode("utf-8")
            
            try:
                with open(PRIV_KEY_FILE, "w") as f:
                    f.write(_private_key)
                with open(PUB_KEY_FILE, "w") as f:
                    f.write(_public_key)
            except Exception as e:
                pass
    return _private_key, _public_key

def get_jwks() -> Dict[str, Any]:
    """Get the JWKS for public verification."""
    _, pub_pem = get_or_generate_rsa_key()
    # jose jwk.construct needs a dict for RSA or string
    key = jwk.construct(pub_pem, algorithm="RS256")
    jwk_dict = key.to_dict()
    jwk_dict["kid"] = _kid
    jwk_dict["use"] = "sig"
    return {"keys": [jwk_dict]}

def generate_crypto_random_string(length: int = 43) -> str:
    """Generate a secure random string (URL-safe)."""
    return secrets.token_urlsafe(length)

def hash_token(token: str) -> str:
    """Hash a token using SHA-256 for secure DB storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def verify_pkce(code_verifier: str, code_challenge: str, method: str = "S256") -> bool:
    """Verify PKCE challenge."""
    if method != "S256":
        return False
    # Base64URL-encode the SHA-256 hash of the verifier
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    expected_challenge = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
    return secrets.compare_digest(expected_challenge, code_challenge)

class OAuthService:
    @staticmethod
    async def create_client(db: AsyncSession, client_name: str, redirect_uris: list, scopes: list) -> OAuthClient:
        client_id = generate_crypto_random_string(32)
        # Assuming public client for now, no secret
        client = OAuthClient(
            client_id=client_id,
            client_name=client_name,
            redirect_uris={"uris": redirect_uris},
            grant_types={"types": ["authorization_code", "refresh_token"]},
            response_types={"types": ["code"]},
            scopes={"scopes": scopes}
        )
        db.add(client)
        await db.commit()
        await db.refresh(client)
        return client

    @staticmethod
    async def get_client(db: AsyncSession, client_id: str) -> Optional[OAuthClient]:
        stmt = select(OAuthClient).where(OAuthClient.client_id == client_id)
        result = await db.execute(stmt)
        return result.scalars().first()

    @staticmethod
    async def create_authorization_code(
        db: AsyncSession, client_id: str, user_id: str, redirect_uri: str, scope: str, code_challenge: str, code_challenge_method: str = "S256"
    ) -> str:
        code = generate_crypto_random_string(64)
        hashed_code = hash_token(code)
        
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        
        auth_code = OAuthAuthorizationCode(
            code_hash=hashed_code,
            client_id=client_id,
            user_id=user_id,
            redirect_uri=redirect_uri,
            scope=scope,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            expires_at=expires_at
        )
        db.add(auth_code)
        await db.commit()
        
        return code

    @staticmethod
    async def exchange_code_for_tokens(
        db: AsyncSession, client_id: str, code: str, redirect_uri: str, code_verifier: str
    ) -> Tuple[Optional[str], Optional[str], Optional[dict]]:
        """Exchange auth code for access & refresh tokens."""
        hashed_code = hash_token(code)
        
        stmt = select(OAuthAuthorizationCode).where(
            OAuthAuthorizationCode.code_hash == hashed_code,
            OAuthAuthorizationCode.client_id == client_id
        )
        result = await db.execute(stmt)
        auth_code = result.scalars().first()
        
        if not auth_code:
            return None, None, {"error": "invalid_grant", "error_description": "Invalid authorization code."}
            
        if auth_code.used_at:
            # Code was already used! Revoke related tokens if possible (threat mitigation).
            return None, None, {"error": "invalid_grant", "error_description": "Authorization code has already been used."}
            
        if auth_code.expires_at < datetime.now(timezone.utc):
            return None, None, {"error": "invalid_grant", "error_description": "Authorization code expired."}
            
        if auth_code.redirect_uri != redirect_uri:
            return None, None, {"error": "invalid_grant", "error_description": "Redirect URI mismatch."}
            
        if not verify_pkce(code_verifier, auth_code.code_challenge, auth_code.code_challenge_method):
            return None, None, {"error": "invalid_grant", "error_description": "PKCE verification failed."}
            
        # Mark code as used
        auth_code.used_at = datetime.now(timezone.utc)
        
        # Issue tokens
        access_token, expires_in = OAuthService._issue_access_token(
            user_id=auth_code.user_id, client_id=client_id, scope=auth_code.scope
        )
        
        refresh_token = await OAuthService._issue_refresh_token(
            db=db, user_id=auth_code.user_id, client_id=client_id, scope=auth_code.scope
        )
        
        await db.commit()
        
        return access_token, refresh_token, {"expires_in": expires_in, "scope": auth_code.scope}

    @staticmethod
    async def rotate_refresh_token(
        db: AsyncSession, client_id: str, refresh_token: str
    ) -> Tuple[Optional[str], Optional[str], Optional[dict]]:
        """Refresh token rotation flow."""
        hashed_token = hash_token(refresh_token)
        
        stmt = select(OAuthRefreshToken).where(
            OAuthRefreshToken.token_hash == hashed_token,
            OAuthRefreshToken.client_id == client_id
        )
        result = await db.execute(stmt)
        rt_record = result.scalars().first()
        
        if not rt_record:
            return None, None, {"error": "invalid_grant", "error_description": "Invalid refresh token."}
            
        if rt_record.revoked_at:
            # Token reuse detected! Revoke the entire family.
            revoke_stmt = delete(OAuthRefreshToken).where(
                OAuthRefreshToken.token_family_id == rt_record.token_family_id
            )
            await db.execute(revoke_stmt)
            await db.commit()
            return None, None, {"error": "invalid_grant", "error_description": "Refresh token reuse detected. Family revoked."}
            
        if rt_record.expires_at < datetime.now(timezone.utc):
            return None, None, {"error": "invalid_grant", "error_description": "Refresh token expired."}
            
        # Mark old refresh token as revoked
        rt_record.revoked_at = datetime.now(timezone.utc)
        
        # Issue new tokens
        access_token, expires_in = OAuthService._issue_access_token(
            user_id=rt_record.user_id, client_id=client_id, scope=rt_record.scope
        )
        
        new_refresh_token = await OAuthService._issue_refresh_token(
            db=db, user_id=rt_record.user_id, client_id=client_id, scope=rt_record.scope,
            family_id=rt_record.token_family_id, rotated_from=hashed_token
        )
        
        await db.commit()
        
        return access_token, new_refresh_token, {"expires_in": expires_in, "scope": rt_record.scope}

    @staticmethod
    def _issue_access_token(user_id: str, client_id: str, scope: str) -> Tuple[str, int]:
        """Issue a JWT access token signed with RS256."""
        priv_key, _ = get_or_generate_rsa_key()
        
        # Determine base URL dynamically or from settings
        # (Assuming 'https://auth.menukit.com' for now, should ideally use config)
        issuer = settings.API_V1_PREFIX # or a proper domain
        
        now = int(time.time())
        expires_in = 86400 * 30 # 30 days
        
        payload = {
            "iss": "menukit-auth", # Placeholder
            "sub": user_id,
            "aud": "menukit-mcp",
            "scope": scope,
            "iat": now,
            "exp": now + expires_in,
            "client_id": client_id,
            "jti": generate_crypto_random_string(16)
        }
        
        token = jwt.encode(payload, priv_key, algorithm="RS256", headers={"kid": _kid})
        return token, expires_in

    @staticmethod
    async def _issue_refresh_token(
        db: AsyncSession, user_id: str, client_id: str, scope: str, family_id: Optional[str] = None, rotated_from: Optional[str] = None
    ) -> str:
        """Issue a secure long-lived refresh token."""
        token = generate_crypto_random_string(64)
        hashed_token = hash_token(token)
        
        if not family_id:
            family_id = generate_crypto_random_string(32)
            
        # Valid for 30 days
        expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        
        rt = OAuthRefreshToken(
            token_hash=hashed_token,
            client_id=client_id,
            user_id=user_id,
            scope=scope,
            token_family_id=family_id,
            rotated_from=rotated_from,
            expires_at=expires_at
        )
        
        db.add(rt)
        return token
