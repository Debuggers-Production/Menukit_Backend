"""Authentication service handling login flow."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, create_refresh_token, verify_refresh_token
from app.core.config import get_settings
from app.models.user import User
from app.models.session import Session
from app.models.activity_log import ActivityLog

settings = get_settings()


class AuthService:
    """Handles user authentication, session management."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create_user(self, email: str) -> User:
        """Get existing user or create a new one by email."""
        result = await self.db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if not user:
            user = User(email=email, role="owner")
            self.db.add(user)
            await self.db.flush()

        return user

    async def create_session(
        self,
        user: User,
        device_info: Optional[str] = None,
        browser_info: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> dict:
        """Create a new session with JWT tokens."""
        token_data = {"sub": str(user.id), "email": user.email, "role": user.role}

        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data)

        session = Session(
            user_id=user.id,
            access_token=access_token,
            refresh_token=refresh_token,
            device_info=device_info,
            browser_info=browser_info,
            ip_address=ip_address,
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
        )
        self.db.add(session)

        # Update last login
        user.last_login = datetime.now(timezone.utc)

        # Log activity
        activity = ActivityLog(
            user_id=user.id,
            action="login",
            details=f"Login from {browser_info or 'unknown browser'}",
            ip_address=ip_address,
        )
        self.db.add(activity)

        await self.db.flush()

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
        }

    async def refresh_session(self, refresh_token_str: str) -> Optional[dict]:
        """Refresh an access token using a refresh token."""
        payload = verify_refresh_token(refresh_token_str)
        if not payload:
            return None

        user_id = payload.get("sub")
        result = await self.db.execute(select(User).where(User.id == uuid.UUID(user_id)))
        user = result.scalar_one_or_none()

        if not user or not user.is_active:
            return None

        token_data = {"sub": str(user.id), "email": user.email, "role": user.role}
        new_access_token = create_access_token(token_data)

        return {
            "access_token": new_access_token,
            "refresh_token": refresh_token_str,
            "token_type": "bearer",
        }

    async def logout(self, user_id: uuid.UUID, ip_address: Optional[str] = None):
        """Invalidate user sessions and log the action."""
        # Deactivate all active sessions
        result = await self.db.execute(
            select(Session).where(Session.user_id == user_id, Session.is_active == True)
        )
        sessions = result.scalars().all()
        for session in sessions:
            session.is_active = False

        # Log activity
        activity = ActivityLog(
            user_id=user_id,
            action="logout",
            ip_address=ip_address,
        )
        self.db.add(activity)
        await self.db.flush()

    async def get_user_by_id(self, user_id: uuid.UUID) -> Optional[User]:
        """Get user by ID."""
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()
