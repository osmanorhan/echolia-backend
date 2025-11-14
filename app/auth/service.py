"""
Authentication service business logic.
"""
import time
import structlog
from typing import Optional, List, Tuple

from app.auth.models import (
    RegisterRequest, PairDeviceRequest, DeviceInfo, UserInfo
)
from app.auth.crypto import (
    create_access_token, create_refresh_token, verify_token,
    validate_public_key, generate_device_id, generate_user_id
)
from app.database import TursoDatabaseManager


logger = structlog.get_logger()


class AuthService:
    """Authentication service for user and device management."""

    def __init__(self, db_manager: TursoDatabaseManager):
        self.db_manager = db_manager

    async def register_user(
        self,
        request: RegisterRequest
    ) -> Tuple[str, str, str, str]:
        """
        Register a new anonymous user with their first device.

        Args:
            request: Registration request with device info

        Returns:
            Tuple of (user_id, device_id, access_token, refresh_token)
        """
        # Validate public key
        if not validate_public_key(request.public_key):
            raise ValueError("Invalid public key format")

        # Generate IDs
        user_id = generate_user_id()
        device_id = generate_device_id()

        logger.info("registering_user", user_id=user_id, device_id=device_id)

        try:
            # Create user's database
            await self.db_manager.create_user_database(user_id)

            # Get user's database
            db = self.db_manager.get_user_db(user_id)

            # Store device info
            now = int(time.time())
            db.execute(
                """
                INSERT INTO device_info
                (device_id, device_name, device_type, platform, public_key, last_sync_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    device_id,
                    request.device_name,
                    request.device_type,
                    request.platform,
                    request.public_key,
                    now,
                    now
                ]
            )
            self.db_manager.commit_and_sync(db, user_id)

            # Create tokens
            access_token = create_access_token(user_id, device_id)
            refresh_token = create_refresh_token(user_id, device_id)

            logger.info("user_registered", user_id=user_id, device_id=device_id)

            return user_id, device_id, access_token, refresh_token

        except Exception as e:
            logger.error("registration_failed", user_id=user_id, error=str(e))
            raise

    async def pair_device(
        self,
        user_id: str,
        request: PairDeviceRequest
    ) -> Tuple[str, str, str]:
        """
        Pair a new device to an existing user account.

        Args:
            user_id: User's UUID
            request: Device pairing request

        Returns:
            Tuple of (device_id, access_token, refresh_token)
        """
        # Validate public key
        if not validate_public_key(request.public_key):
            raise ValueError("Invalid public key format")

        device_id = generate_device_id()

        logger.info("pairing_device", user_id=user_id, device_id=device_id)

        try:
            # Get user's database
            db = self.db_manager.get_user_db(user_id)

            # Store device info
            now = int(time.time())
            db.execute(
                """
                INSERT INTO device_info
                (device_id, device_name, device_type, platform, public_key, last_sync_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    device_id,
                    request.device_name,
                    request.device_type,
                    request.platform,
                    request.public_key,
                    now,
                    now
                ]
            )
            self.db_manager.commit_and_sync(db, user_id)

            # Create tokens
            access_token = create_access_token(user_id, device_id)
            refresh_token = create_refresh_token(user_id, device_id)

            logger.info("device_paired", user_id=user_id, device_id=device_id)

            return device_id, access_token, refresh_token

        except Exception as e:
            logger.error("pairing_failed", user_id=user_id, error=str(e))
            raise

    def get_devices(self, user_id: str) -> List[DeviceInfo]:
        """
        Get all devices for a user.

        Args:
            user_id: User's UUID

        Returns:
            List of device information
        """
        try:
            db = self.db_manager.get_user_db(user_id)

            result = db.execute(
                "SELECT device_id, device_name, device_type, platform, public_key, last_sync_at, created_at FROM device_info"
            )

            devices = []
            for row in result.rows:
                devices.append(DeviceInfo(
                    device_id=row[0],
                    device_name=row[1],
                    device_type=row[2],
                    platform=row[3],
                    public_key=row[4],
                    last_sync_at=row[5],
                    created_at=row[6]
                ))

            return devices

        except Exception as e:
            logger.error("get_devices_failed", user_id=user_id, error=str(e))
            raise

    async def revoke_device(self, user_id: str, device_id: str) -> bool:
        """
        Revoke a device's access.

        Args:
            user_id: User's UUID
            device_id: Device's UUID

        Returns:
            True if revoked successfully
        """
        try:
            db = self.db_manager.get_user_db(user_id)

            db.execute(
                "DELETE FROM device_info WHERE device_id = ?",
                [device_id]
            )
            self.db_manager.commit_and_sync(db, user_id)

            logger.info("device_revoked", user_id=user_id, device_id=device_id)
            return True

        except Exception as e:
            logger.error("revoke_failed", user_id=user_id, device_id=device_id, error=str(e))
            return False

    def verify_device(self, user_id: str, device_id: str) -> bool:
        """
        Verify that a device belongs to a user.

        Args:
            user_id: User's UUID
            device_id: Device's UUID

        Returns:
            True if device is valid
        """
        try:
            db = self.db_manager.get_user_db(user_id)

            result = db.execute(
                "SELECT device_id FROM device_info WHERE device_id = ?",
                [device_id]
            )

            return len(result.rows) > 0

        except Exception as e:
            logger.error("verify_device_failed", user_id=user_id, error=str(e))
            return False

    def refresh_access_token(
        self,
        refresh_token: str
    ) -> Optional[Tuple[str, str]]:
        """
        Refresh access token using refresh token.

        Args:
            refresh_token: Refresh token

        Returns:
            Tuple of (new_access_token, new_refresh_token) or None
        """
        payload = verify_token(refresh_token)

        if not payload or payload.get("type") != "refresh":
            return None

        user_id = payload.get("sub")
        device_id = payload.get("device_id")

        if not user_id or not device_id:
            return None

        # Verify device still exists
        if not self.verify_device(user_id, device_id):
            return None

        # Create new tokens
        access_token = create_access_token(user_id, device_id)
        new_refresh_token = create_refresh_token(user_id, device_id)

        return access_token, new_refresh_token
