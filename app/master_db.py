"""
Master database manager for users, devices, add-ons, and subscriptions.

Unlike per-user databases, this is a single centralized database
that stores user identities, OAuth info, devices, and add-on subscriptions.
"""
import asyncio
import httpx
import structlog
import time
from typing import Optional, Dict, List, Any

import libsql

from app.config import settings


logger = structlog.get_logger()


class MasterDatabaseManager:
    """
    Manages the master database for Echolia.

    Schema:
    - users: OAuth identities (Google, Apple)
    - user_devices: Registered devices per user
    - user_add_ons: Active subscriptions and add-ons
    - receipts: Purchase verification records
    - ai_usage_quota: Anti-abuse rate limiting
    """

    def __init__(self):
        self.turso_org_url = settings.turso_org_url
        self.auth_token = settings.turso_auth_token
        self.db_name = "echolia-master"
        self._connection: Optional[any] = None

        logger.info("master_db_manager_initialized", db_name=self.db_name)

    def _get_db_url(self) -> str:
        """Generate Turso database URL for master database."""
        if settings.master_db_url:
            return settings.master_db_url
        return f"libsql://{self.db_name}-{self.turso_org_url}"

    async def _generate_db_token(self) -> str:
        """Generate a short-lived token for master DB access."""
        try:
            async with httpx.AsyncClient() as client:
                url = f"https://api.turso.tech/v1/organizations/{self.turso_org_url.split('.')[0]}/databases/{self.db_name}/auth/tokens?expiration=1d"
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {self.auth_token}"},
                    timeout=10.0
                )
                if response.status_code == 200:
                    return response.json().get("jwt")
                else:
                    raise Exception(f"Failed to generate token: {response.text}")
        except Exception as e:
            logger.error("master_token_generation_failed", error=str(e))
            raise

    async def get_connection_async(self):
        """Async version of get_connection to support token generation."""
        if self._connection is not None:
            return self._connection

        db_url = self._get_db_url()
        token = await self._generate_db_token()

        self._connection = libsql.connect(db_url, auth_token=token)
        logger.info("master_database_connected", db_name=self.db_name)
        # Note: _ensure_schema needs to be called carefully as it is sync
        # For now, we assume schema is checked at startup manually or we refactor _ensure_schema
        return self._connection

    def get_connection(self):
        """
        Get or create database connection to master database.
        """
        if self._connection is not None:
            return self._connection

        if settings.master_db_auth_token:
             # Use configured DB token
             token = settings.master_db_auth_token
             db_url = self._get_db_url()
             self._connection = libsql.connect(db_url, auth_token=token)
             self._ensure_schema()
             return self._connection

        # Automatic token generation from platform token
        # Block to get token
        loop = asyncio.get_event_loop()
        if loop.is_running():
             # We are likely inside a FastAPI request handling loop
             pass
             
        # Fallback to sync version using requests
        import requests
        try:
             org = self.turso_org_url.split('.')[0]
             url = f"https://api.turso.tech/v1/organizations/{org}/databases/{self.db_name}/auth/tokens?expiration=1d"
             resp = requests.post(url, headers={"Authorization": f"Bearer {self.auth_token}"}, timeout=10)
             if resp.status_code == 200:
                 token = resp.json().get("jwt")
             else:
                 raise Exception(f"Token gen failed: {resp.text}")
        except Exception as e:
             logger.error("sync_token_gen_failed", error=str(e))
             raise
             
        db_url = self._get_db_url()
        self._connection = libsql.connect(db_url, auth_token=token)
        self._ensure_schema()
        return self._connection



    async def create_master_database(self) -> bool:
        """
        Create the master database via Turso API.

        Returns:
            True if created successfully
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"https://api.turso.tech/v1/organizations/{self.turso_org_url.split('.')[0]}/databases",
                    headers={
                        "Authorization": f"Bearer {self.auth_token}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "name": self.db_name,
                        "group": "default"
                    },
                    timeout=30.0
                )

                if response.status_code in (200, 201):
                    logger.info("master_database_created", db_name=self.db_name)

                    # Initialize schema
                    self._ensure_schema()
                    return True

                elif response.status_code == 409:
                    # Database already exists
                    logger.info("master_database_already_exists", db_name=self.db_name)
                    self._ensure_schema()
                    return True

                else:
                    logger.error(
                        "master_database_creation_failed",
                        status=response.status_code,
                        response=response.text
                    )
                    return False

        except Exception as e:
            logger.error("master_database_creation_error", error=str(e))
            raise

    def _ensure_schema(self) -> None:
        """
        Ensure database has correct schema version.
        Runs migrations if needed.
        """
        try:
            conn = self.get_connection()

            # Check if schema_version table exists
            result = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
            )
            rows = result.fetchall()

            if not rows:
                # No schema yet, run initial migration
                logger.info("initializing_master_schema")
                self._run_migration_v001()
            else:
                # Check current version
                result = conn.execute(
                    "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
                )
                version_rows = result.fetchall()

                current_version = version_rows[0][0] if version_rows else 0
                logger.info("master_schema_version_check", version=current_version)

                # Run any pending migrations
                if current_version < 1:
                    self._run_migration_v001()

        except Exception as e:
            logger.error("master_schema_check_failed", error=str(e))
            raise

    def _run_migration_v001(self) -> None:
        """Run initial master database schema migration."""
        conn = self.get_connection()

        migration_sql = """
        -- Schema version tracking
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at INTEGER NOT NULL
        );

        -- Users (OAuth identities)
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            provider_user_id TEXT NOT NULL,
            email TEXT,
            name TEXT,
            created_at INTEGER NOT NULL,
            UNIQUE(provider, provider_user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_users_provider ON users(provider, provider_user_id);

        -- User devices
        CREATE TABLE IF NOT EXISTS user_devices (
            device_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            device_name TEXT NOT NULL,
            platform TEXT NOT NULL,
            app_version TEXT,
            last_seen_at INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_devices_user ON user_devices(user_id);
        CREATE INDEX IF NOT EXISTS idx_devices_last_seen ON user_devices(last_seen_at);

        -- User add-ons (subscriptions)
        CREATE TABLE IF NOT EXISTS user_add_ons (
            user_id TEXT NOT NULL,
            add_on_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            platform TEXT NOT NULL,
            product_id TEXT NOT NULL,
            transaction_id TEXT NOT NULL,
            original_transaction_id TEXT,
            purchase_date INTEGER NOT NULL,
            expires_at INTEGER,
            auto_renew INTEGER DEFAULT 0,
            cancelled_at INTEGER,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            PRIMARY KEY (user_id, add_on_type),
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_add_ons_expires ON user_add_ons(expires_at);
        CREATE INDEX IF NOT EXISTS idx_add_ons_status ON user_add_ons(status);

        -- Purchase receipts
        CREATE TABLE IF NOT EXISTS receipts (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            platform TEXT NOT NULL,
            receipt_data TEXT NOT NULL,
            product_id TEXT NOT NULL,
            transaction_id TEXT NOT NULL,
            verified_at INTEGER NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_receipts_user ON receipts(user_id);
        CREATE INDEX IF NOT EXISTS idx_receipts_transaction ON receipts(transaction_id);

        -- AI usage quota (anti-abuse rate limiting)
        CREATE TABLE IF NOT EXISTS ai_usage_quota (
            user_id TEXT NOT NULL,
            date TEXT NOT NULL,
            request_count INTEGER DEFAULT 0,
            last_reset_at INTEGER NOT NULL,
            PRIMARY KEY (user_id, date),
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_quota_date ON ai_usage_quota(date);

        -- Record migration
        INSERT INTO schema_version (version, applied_at)
        VALUES (1, strftime('%s', 'now'));
        """

        self._execute_sql_script(conn, migration_sql)
        logger.info("master_migration_v001_completed")

    @staticmethod
    def _execute_sql_script(conn, sql: str) -> None:
        """
        Execute a SQL script containing multiple statements.

        libsql/Hrana requires one statement per execute call.
        """
        statements = [s.strip() for s in sql.strip().split(";") if s.strip()]
        for statement in statements:
            conn.execute(statement)
        conn.commit()

    # ========== User Management ==========

    def create_user(
        self,
        user_id: str,
        provider: str,
        provider_user_id: str,
        email: Optional[str] = None,
        name: Optional[str] = None
    ) -> bool:
        """
        Create a new user from OAuth provider info.

        Args:
            user_id: Generated UUID for user
            provider: 'google' or 'apple'
            provider_user_id: Provider's user ID (sub claim)
            email: User email (may be null for Apple)
            name: User name (may be null)

        Returns:
            True if created successfully
        """
        conn = self.get_connection()

        try:
            current_time = int(time.time())

            conn.execute(
                """
                INSERT INTO users (user_id, provider, provider_user_id, email, name, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [user_id, provider, provider_user_id, email, name, current_time]
            )
            conn.commit()

            logger.info("user_created", user_id=user_id, provider=provider)
            return True

        except Exception as e:
            logger.error("user_creation_failed", user_id=user_id, error=str(e))
            raise

    def get_user_by_provider(self, provider: str, provider_user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get user by OAuth provider and provider user ID.

        Args:
            provider: 'google' or 'apple'
            provider_user_id: Provider's user ID

        Returns:
            User dict or None
        """
        conn = self.get_connection()

        try:
            result = conn.execute(
                "SELECT user_id, provider, provider_user_id, email, name, created_at FROM users WHERE provider = ? AND provider_user_id = ?",
                [provider, provider_user_id]
            )

            rows = result.fetchall()

            if rows:
                row = rows[0]
                return {
                    "user_id": row[0],
                    "provider": row[1],
                    "provider_user_id": row[2],
                    "email": row[3],
                    "name": row[4],
                    "created_at": row[5]
                }

            return None

        except Exception as e:
            logger.error("get_user_by_provider_failed", provider=provider, error=str(e))
            raise

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get user by user_id.

        Args:
            user_id: User UUID

        Returns:
            User dict or None
        """
        conn = self.get_connection()

        try:
            result = conn.execute(
                "SELECT user_id, provider, provider_user_id, email, name, created_at FROM users WHERE user_id = ?",
                [user_id]
            )

            rows = result.fetchall()

            if rows:
                row = rows[0]
                return {
                    "user_id": row[0],
                    "provider": row[1],
                    "provider_user_id": row[2],
                    "email": row[3],
                    "name": row[4],
                    "created_at": row[5]
                }

            return None

        except Exception as e:
            logger.error("get_user_failed", user_id=user_id, error=str(e))
            raise

    # ========== Device Management ==========

    def register_device(
        self,
        device_id: str,
        user_id: str,
        device_name: str,
        platform: str,
        app_version: Optional[str] = None
    ) -> bool:
        """
        Register a device for a user.

        Args:
            device_id: Platform device ID
            user_id: User UUID
            device_name: Device name
            platform: 'ios', 'android', 'macos', 'windows', 'linux'
            app_version: App version string

        Returns:
            True if registered successfully
        """
        conn = self.get_connection()

        try:
            current_time = int(time.time())

            # Upsert device (update if exists, insert if not)
            conn.execute(
                """
                INSERT INTO user_devices (device_id, user_id, device_name, platform, app_version, last_seen_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                    device_name = excluded.device_name,
                    platform = excluded.platform,
                    app_version = excluded.app_version,
                    last_seen_at = excluded.last_seen_at
                """,
                [device_id, user_id, device_name, platform, app_version, current_time, current_time]
            )
            conn.commit()

            logger.info("device_registered", device_id=device_id, user_id=user_id, platform=platform)
            return True

        except Exception as e:
            logger.error("device_registration_failed", device_id=device_id, error=str(e))
            raise

    def get_user_devices(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Get all devices for a user.

        Args:
            user_id: User UUID

        Returns:
            List of device dicts
        """
        conn = self.get_connection()

        try:
            result = conn.execute(
                """
                SELECT device_id, user_id, device_name, platform, app_version, last_seen_at, created_at
                FROM user_devices
                WHERE user_id = ?
                ORDER BY last_seen_at DESC
                """,
                [user_id]
            )

            rows = result.fetchall()
            devices = []
            for row in rows:
                devices.append({
                    "device_id": row[0],
                    "user_id": row[1],
                    "device_name": row[2],
                    "platform": row[3],
                    "app_version": row[4],
                    "last_seen_at": row[5],
                    "created_at": row[6]
                })

            return devices

        except Exception as e:
            logger.error("get_user_devices_failed", user_id=user_id, error=str(e))
            raise

    def delete_device(self, device_id: str, user_id: str) -> bool:
        """
        Delete a device.

        Args:
            device_id: Device ID
            user_id: User ID (for verification)

        Returns:
            True if deleted
        """
        conn = self.get_connection()

        try:
            conn.execute(
                "DELETE FROM user_devices WHERE device_id = ? AND user_id = ?",
                [device_id, user_id]
            )
            conn.commit()

            logger.info("device_deleted", device_id=device_id, user_id=user_id)
            return True

        except Exception as e:
            logger.error("device_deletion_failed", device_id=device_id, error=str(e))
            raise

    # ========== Add-Ons Management ==========

    def get_user_add_ons(self, user_id: str) -> Dict[str, Any]:
        """
        Get all add-ons for a user.

        Args:
            user_id: User UUID

        Returns:
            Dict with add-on status
        """
        conn = self.get_connection()

        try:
            current_time = int(time.time())

            result = conn.execute(
                """
                SELECT add_on_type, status, platform, product_id, transaction_id,
                       purchase_date, expires_at, auto_renew, cancelled_at
                FROM user_add_ons
                WHERE user_id = ?
                """,
                [user_id]
            )

            rows = result.fetchall()
            add_ons = {
                "sync_enabled": False,
                "ai_enabled": False,
                "supporter": False,
                "details": []
            }

            for row in rows:
                add_on_type = row[0]
                status = row[1]
                expires_at = row[6]

                # Check if active and not expired
                is_active = (
                    status == "active" and
                    (expires_at is None or expires_at > current_time)
                )

                if is_active:
                    if add_on_type == "sync":
                        add_ons["sync_enabled"] = True
                    elif add_on_type == "ai":
                        add_ons["ai_enabled"] = True
                    elif add_on_type == "supporter":
                        add_ons["supporter"] = True

                add_ons["details"].append({
                    "add_on_type": add_on_type,
                    "status": status,
                    "platform": row[2],
                    "product_id": row[3],
                    "transaction_id": row[4],
                    "purchase_date": row[5],
                    "expires_at": expires_at,
                    "auto_renew": bool(row[7]),
                    "cancelled_at": row[8],
                    "is_active": is_active
                })

            return add_ons

        except Exception as e:
            logger.error("get_user_add_ons_failed", user_id=user_id, error=str(e))
            raise

    def activate_add_on(
        self,
        user_id: str,
        add_on_type: str,
        platform: str,
        product_id: str,
        transaction_id: str,
        original_transaction_id: Optional[str],
        purchase_date: int,
        expires_at: Optional[int],
        auto_renew: bool
    ) -> bool:
        """
        Activate an add-on after purchase verification.

        Args:
            user_id: User UUID
            add_on_type: 'sync', 'ai', or 'supporter'
            platform: 'ios' or 'android'
            product_id: Store product ID
            transaction_id: Store transaction ID
            original_transaction_id: Original transaction ID (subscriptions)
            purchase_date: Purchase timestamp
            expires_at: Expiration timestamp (None for one-time)
            auto_renew: Auto-renewal enabled

        Returns:
            True if activated
        """
        conn = self.get_connection()

        try:
            current_time = int(time.time())

            conn.execute(
                """
                INSERT INTO user_add_ons (
                    user_id, add_on_type, status, platform, product_id, transaction_id,
                    original_transaction_id, purchase_date, expires_at, auto_renew,
                    created_at, updated_at
                )
                VALUES (?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, add_on_type) DO UPDATE SET
                    status = 'active',
                    platform = excluded.platform,
                    product_id = excluded.product_id,
                    transaction_id = excluded.transaction_id,
                    original_transaction_id = excluded.original_transaction_id,
                    purchase_date = excluded.purchase_date,
                    expires_at = excluded.expires_at,
                    auto_renew = excluded.auto_renew,
                    cancelled_at = NULL,
                    updated_at = excluded.updated_at
                """,
                [
                    user_id, add_on_type, platform, product_id, transaction_id,
                    original_transaction_id, purchase_date, expires_at,
                    1 if auto_renew else 0, current_time, current_time
                ]
            )
            conn.commit()

            logger.info(
                "add_on_activated",
                user_id=user_id,
                add_on_type=add_on_type,
                expires_at=expires_at
            )
            return True

        except Exception as e:
            logger.error("add_on_activation_failed", user_id=user_id, error=str(e))
            raise

    def is_add_on_active(self, user_id: str, add_on_type: str) -> bool:
        """
        Check if a specific add-on is active for a user.

        Args:
            user_id: User UUID
            add_on_type: 'sync', 'ai', or 'supporter'

        Returns:
            True if active
        """
        conn = self.get_connection()

        try:
            current_time = int(time.time())

            result = conn.execute(
                """
                SELECT status, expires_at
                FROM user_add_ons
                WHERE user_id = ? AND add_on_type = ?
                """,
                [user_id, add_on_type]
            )

            rows = result.fetchall()

            if not rows:
                return False

            row = rows[0]
            status = row[0]
            expires_at = row[1]

            # Active if status is 'active' and not expired
            return status == "active" and (expires_at is None or expires_at > current_time)

        except Exception as e:
            logger.error("is_add_on_active_failed", user_id=user_id, error=str(e))
            return False

    def close_connection(self) -> None:
        """Close database connection."""
        if self._connection:
            try:
                self._connection.close()
                logger.info("master_database_connection_closed")
            except Exception as e:
                logger.error("master_database_close_failed", error=str(e))

            self._connection = None


# Global master database manager instance
master_db_manager = MasterDatabaseManager()


def get_master_db_manager() -> MasterDatabaseManager:
    """Dependency injection for master database manager."""
    return master_db_manager
