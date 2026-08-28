"""OAuth 2.1 database models."""

from datetime import datetime, timezone
from sqlalchemy import String, Boolean, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.database.base import Base, UUIDMixin, TimestampMixin


class OAuthClient(Base, UUIDMixin, TimestampMixin):
    """OAuth 2.1 registered client."""
    __tablename__ = "oauth_clients"

    client_id: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    client_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)  # Optional for public clients
    client_name: Mapped[str] = mapped_column(String(255), nullable=False)
    redirect_uris: Mapped[dict] = mapped_column(JSON, nullable=False)  # List of allowed URIs
    grant_types: Mapped[dict] = mapped_column(JSON, nullable=False)    # List of grant types
    response_types: Mapped[dict] = mapped_column(JSON, nullable=False) # List of response types
    token_endpoint_auth_method: Mapped[str] = mapped_column(String(50), default="none")
    scopes: Mapped[dict] = mapped_column(JSON, nullable=False)         # List of allowed scopes


class OAuthAuthorizationCode(Base, UUIDMixin, TimestampMixin):
    """Short-lived authorization code."""
    __tablename__ = "oauth_auth_codes"

    code_hash: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    client_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(512), nullable=False)
    scope: Mapped[str] = mapped_column(String(512), nullable=False)
    code_challenge: Mapped[str] = mapped_column(String(255), nullable=False)
    code_challenge_method: Mapped[str] = mapped_column(String(50), nullable=False, default="S256")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OAuthRefreshToken(Base, UUIDMixin, TimestampMixin):
    """Long-lived refresh token."""
    __tablename__ = "oauth_refresh_tokens"

    token_hash: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    client_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    scope: Mapped[str] = mapped_column(String(512), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rotated_from: Mapped[str | None] = mapped_column(String(255), nullable=True)
    token_family_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
