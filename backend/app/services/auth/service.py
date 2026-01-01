"""
Authentication service for user management and token handling.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

import bcrypt
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.db.models import User, RefreshToken, UserPreference
from app.core.config import settings
from app.core.logging import get_logger
from .jwt import create_access_token, create_refresh_token, verify_token

logger = get_logger(__name__)


class AuthService:
    """Service for authentication and user management."""

    def __init__(self):
        self.access_token_expire = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        self.refresh_token_expire = timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    def hash_password(self, password: str) -> str:
        """Hash a password using bcrypt."""
        # Encode password to bytes, truncate to 72 bytes (bcrypt limit)
        password_bytes = password.encode('utf-8')[:72]
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password_bytes, salt)
        return hashed.decode('utf-8')

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a password against a hash."""
        try:
            password_bytes = plain_password.encode('utf-8')[:72]
            hashed_bytes = hashed_password.encode('utf-8')
            return bcrypt.checkpw(password_bytes, hashed_bytes)
        except Exception:
            return False

    async def register(
        self,
        email: str,
        password: str,
        display_name: str | None = None,
    ) -> dict:
        """Register a new user."""
        async with AsyncSessionLocal() as session:
            # Check if email exists
            result = await session.execute(
                select(User).where(User.email == email.lower())
            )
            existing = result.scalar_one_or_none()

            if existing:
                return {"error": "Email already registered"}

            # Create user
            user = User(
                email=email.lower(),
                hashed_password=self.hash_password(password),
                name=display_name,
            )
            session.add(user)
            await session.flush()

            # Create default preferences
            preferences = UserPreference(
                user_id=user.id,
                topics=["tech", "security", "ai-ml"],
                email_daily=True,
            )
            session.add(preferences)

            await session.commit()

            # Generate tokens
            access_token = create_access_token(user.id)
            refresh_token = await self._create_refresh_token(session, user.id)

            return {
                "user": {
                    "id": str(user.id),
                    "email": user.email,
                    "name": user.name,
                },
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
            }

    async def login(self, email: str, password: str) -> dict:
        """Authenticate a user and return tokens."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.email == email.lower())
            )
            user = result.scalar_one_or_none()

            if not user:
                return {"error": "Invalid email or password"}

            if not self.verify_password(password, user.hashed_password):
                return {"error": "Invalid email or password"}

            # Generate tokens
            access_token = create_access_token(user.id)
            refresh_token = await self._create_refresh_token(session, user.id)

            return {
                "user": {
                    "id": str(user.id),
                    "email": user.email,
                    "name": user.name,
                },
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
            }

    async def refresh_tokens(self, refresh_token: str) -> dict:
        """Refresh access and refresh tokens."""
        # Verify the refresh token
        payload = verify_token(refresh_token, token_type="refresh")
        if not payload:
            return {"error": "Invalid or expired refresh token"}

        user_id = UUID(payload.sub)
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()

        async with AsyncSessionLocal() as session:
            # Check if refresh token exists in database
            result = await session.execute(
                select(RefreshToken).where(
                    RefreshToken.user_id == user_id,
                    RefreshToken.token_hash == token_hash,
                    RefreshToken.revoked_at == None,
                )
            )
            token_record = result.scalar_one_or_none()

            if not token_record:
                return {"error": "Refresh token not found or revoked"}

            # Revoke old refresh token
            token_record.revoked_at = datetime.now(timezone.utc)

            # Get user
            user_result = await session.execute(
                select(User).where(User.id == user_id)
            )
            user = user_result.scalar_one_or_none()

            if not user:
                return {"error": "User not found"}

            # Generate new tokens
            new_access_token = create_access_token(user_id)
            new_refresh_token = await self._create_refresh_token(session, user_id)

            return {
                "access_token": new_access_token,
                "refresh_token": new_refresh_token,
                "token_type": "bearer",
            }

    async def logout(self, user_id: UUID, refresh_token: str | None = None) -> dict:
        """Logout user by revoking refresh tokens."""
        async with AsyncSessionLocal() as session:
            if refresh_token:
                # Revoke specific token
                token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
                result = await session.execute(
                    select(RefreshToken).where(
                        RefreshToken.user_id == user_id,
                        RefreshToken.token_hash == token_hash,
                    )
                )
                token_record = result.scalar_one_or_none()
                if token_record:
                    token_record.revoked_at = datetime.now(timezone.utc)
            else:
                # Revoke all user's refresh tokens
                await session.execute(
                    delete(RefreshToken).where(RefreshToken.user_id == user_id)
                )

            await session.commit()

        return {"success": True}

    async def get_user_by_id(self, user_id: UUID) -> dict | None:
        """Get user by ID."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.id == user_id)
            )
            user = result.scalar_one_or_none()

            if not user:
                return None

            return {
                "id": str(user.id),
                "email": user.email,
                "name": user.name,
                "created_at": user.created_at.isoformat(),
            }

    async def update_user(
        self,
        user_id: UUID,
        name: str | None = None,
        password: str | None = None,
    ) -> dict:
        """Update user profile."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.id == user_id)
            )
            user = result.scalar_one_or_none()

            if not user:
                return {"error": "User not found"}

            if name is not None:
                user.name = name

            if password is not None:
                user.hashed_password = self.hash_password(password)

            await session.commit()

            return {
                "id": str(user.id),
                "email": user.email,
                "name": user.name,
            }

    async def _create_refresh_token(self, session: AsyncSession, user_id: UUID) -> str:
        """Create and store a refresh token."""
        token = create_refresh_token(user_id)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        expires_at = datetime.now(timezone.utc) + self.refresh_token_expire

        token_record = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        session.add(token_record)
        await session.commit()

        return token

    async def cleanup_expired_tokens(self) -> int:
        """Remove expired refresh tokens."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                delete(RefreshToken).where(
                    RefreshToken.expires_at < datetime.now(timezone.utc)
                )
            )
            await session.commit()
            return result.rowcount


# Singleton instance
_auth_service: AuthService | None = None


def get_auth_service() -> AuthService:
    """Get the auth service singleton."""
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service
