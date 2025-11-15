"""
Authentication service business logic for OAuth-based authentication.
"""
import time
import uuid
import structlog
from typing import Optional, List, Tuple

from app.auth.models import (
    OAuthSignInRequest,
    OAuthSignInResponse,
    UserAddOns,
    DeviceInfo,
    UserInfoResponse,
    RefreshTokenResponse
)
from app.auth.crypto import (
    create_access_token,
    create_refresh_token,
    verify_token
)
from app.auth.oauth_verifiers import verify_oauth_token, UserInfo as OAuthUserInfo
from app.master_db import MasterDatabaseManager
from app.database import TursoDatabaseManager


logger = structlog.get_logger()


class AuthService:
    """Authentication service for OAuth-based user and device management."""

    def __init__(
        self,
        master_db: MasterDatabaseManager,
        user_db_manager: TursoDatabaseManager
    ):
        self.master_db = master_db
        self.user_db_manager = user_db_manager

    async def sign_in_with_oauth(
        self,
        request: OAuthSignInRequest
    ) -> OAuthSignInResponse:
        """
        Sign in with OAuth (Google or Apple).

        Flow:
        1. Verify OAuth ID token with provider
        2. Get or create user in master database
        3. Register/update device in master database
        4. Create per-user database if first sign-in
        5. Generate JWT tokens
        6. Return tokens + user info + add-ons

        Args:
            request: OAuth sign-in request

        Returns:
            OAuth sign-in response with tokens and add-ons
        """
        logger.info(
            "oauth_signin_start",
            provider=request.provider,
            device_id=request.device_id,
            platform=request.platform
        )

        # Step 1: Verify OAuth token
        oauth_user_info = verify_oauth_token(request.provider, request.id_token)

        if oauth_user_info is None:
            logger.error("oauth_token_verification_failed", provider=request.provider)
            raise ValueError(f"Invalid {request.provider} token")

        # Step 2: Get or create user
        user_id = await self._get_or_create_user(oauth_user_info)

        # Step 3: Register device
        self.master_db.register_device(
            device_id=request.device_id,
            user_id=user_id,
            device_name=request.device_name,
            platform=request.platform,
            app_version=request.app_version
        )

        # Step 4: Ensure per-user database exists
        await self.user_db_manager.create_user_database(user_id)

        # Step 5: Get user's add-ons
        add_ons_data = self.master_db.get_user_add_ons(user_id)
        add_ons = UserAddOns(
            sync_enabled=add_ons_data["sync_enabled"],
            ai_enabled=add_ons_data["ai_enabled"],
            supporter=add_ons_data["supporter"]
        )

        # Step 6: Generate JWT tokens
        access_token = create_access_token(user_id, request.device_id)
        refresh_token = create_refresh_token(user_id, request.device_id)

        # Calculate expires_in (access token expiration)
        from app.config import settings
        expires_in = settings.access_token_expire_minutes * 60

        logger.info(
            "oauth_signin_success",
            user_id=user_id,
            provider=request.provider,
            device_id=request.device_id
        )

        return OAuthSignInResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=expires_in,
            user_id=user_id,
            add_ons=add_ons
        )

    async def _get_or_create_user(self, oauth_user_info: OAuthUserInfo) -> str:
        """
        Get existing user or create new user from OAuth info.

        Args:
            oauth_user_info: User info from OAuth provider

        Returns:
            User ID (UUID)
        """
        # Check if user exists
        existing_user = self.master_db.get_user_by_provider(
            provider=oauth_user_info.provider,
            provider_user_id=oauth_user_info.provider_user_id
        )

        if existing_user:
            logger.info(
                "user_found",
                user_id=existing_user["user_id"],
                provider=oauth_user_info.provider
            )
            return existing_user["user_id"]

        # Create new user
        user_id = str(uuid.uuid4())

        self.master_db.create_user(
            user_id=user_id,
            provider=oauth_user_info.provider,
            provider_user_id=oauth_user_info.provider_user_id,
            email=oauth_user_info.email,
            name=oauth_user_info.name
        )

        logger.info(
            "user_created",
            user_id=user_id,
            provider=oauth_user_info.provider,
            email=oauth_user_info.email
        )

        return user_id

    def refresh_access_token(
        self,
        refresh_token_str: str
    ) -> Optional[RefreshTokenResponse]:
        """
        Refresh access token using refresh token.

        Args:
            refresh_token_str: Refresh token

        Returns:
            New tokens or None if invalid
        """
        # Verify refresh token
        payload = verify_token(refresh_token_str)

        if not payload or payload.get("type") != "refresh":
            logger.error("refresh_token_invalid_type")
            return None

        user_id = payload.get("sub")
        device_id = payload.get("device_id")

        if not user_id or not device_id:
            logger.error("refresh_token_missing_claims")
            return None

        # Verify user still exists in master DB
        user = self.master_db.get_user(user_id)
        if not user:
            logger.error("refresh_token_user_not_found", user_id=user_id)
            return None

        # Verify device still exists
        devices = self.master_db.get_user_devices(user_id)
        device_exists = any(d["device_id"] == device_id for d in devices)

        if not device_exists:
            logger.error("refresh_token_device_not_found", device_id=device_id)
            return None

        # Create new tokens
        access_token = create_access_token(user_id, device_id)
        new_refresh_token = create_refresh_token(user_id, device_id)

        from app.config import settings
        expires_in = settings.access_token_expire_minutes * 60

        logger.info("token_refreshed", user_id=user_id, device_id=device_id)

        return RefreshTokenResponse(
            access_token=access_token,
            refresh_token=new_refresh_token,
            token_type="bearer",
            expires_in=expires_in
        )

    def get_user_devices(self, user_id: str) -> List[DeviceInfo]:
        """
        Get all devices for a user.

        Args:
            user_id: User UUID

        Returns:
            List of device info
        """
        try:
            devices_data = self.master_db.get_user_devices(user_id)

            devices = [
                DeviceInfo(
                    device_id=d["device_id"],
                    user_id=d["user_id"],
                    device_name=d["device_name"],
                    platform=d["platform"],
                    app_version=d.get("app_version"),
                    last_seen_at=d["last_seen_at"],
                    created_at=d["created_at"]
                )
                for d in devices_data
            ]

            return devices

        except Exception as e:
            logger.error("get_devices_failed", user_id=user_id, error=str(e))
            raise

    async def delete_device(self, user_id: str, device_id: str) -> bool:
        """
        Delete a device for a user.

        Args:
            user_id: User UUID
            device_id: Device ID

        Returns:
            True if deleted successfully
        """
        try:
            result = self.master_db.delete_device(device_id, user_id)
            logger.info("device_deleted", user_id=user_id, device_id=device_id)
            return result

        except Exception as e:
            logger.error("delete_device_failed", user_id=user_id, error=str(e))
            raise

    def get_user_info(self, user_id: str) -> Optional[UserInfoResponse]:
        """
        Get user information.

        Args:
            user_id: User UUID

        Returns:
            User info or None
        """
        try:
            user = self.master_db.get_user(user_id)
            if not user:
                return None

            add_ons_data = self.master_db.get_user_add_ons(user_id)
            add_ons = UserAddOns(
                sync_enabled=add_ons_data["sync_enabled"],
                ai_enabled=add_ons_data["ai_enabled"],
                supporter=add_ons_data["supporter"]
            )

            return UserInfoResponse(
                user_id=user["user_id"],
                provider=user["provider"],
                email=user.get("email"),
                name=user.get("name"),
                created_at=user["created_at"],
                add_ons=add_ons
            )

        except Exception as e:
            logger.error("get_user_info_failed", user_id=user_id, error=str(e))
            raise
