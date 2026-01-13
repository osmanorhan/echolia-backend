"""
Turso database manager with per-user database architecture.
Each user gets their own SQLite database in Turso.
"""
import asyncio
import httpx
import structlog
from functools import lru_cache
from typing import Dict, Optional, List
from pathlib import Path

import libsql

from app.config import settings


logger = structlog.get_logger()


class TursoDatabaseManager:
    """
    Manages per-user Turso databases with embedded replicas.

    Architecture:
    - Each user has their own database: user_{user_id}.db
    - Databases use embedded replicas for local caching on VPS
    - Connections are cached using LRU cache
    - Automatic schema migration on first access
    """

    def __init__(self):
        self.turso_org_url = settings.turso_org_url
        self.auth_token = settings.turso_auth_token
        self.embedded_replica = settings.embedded_replica
        self.sync_interval = settings.sync_interval
        self._connections: Dict[str, any] = {}
        self.data_dir = Path(settings.data_dir)
        self.data_dir.mkdir(exist_ok=True)

        logger.info(
            "turso_manager_initialized",
            org_url=self.turso_org_url,
            embedded_replica=self.embedded_replica
        )

    def _get_db_name(self, user_id: str) -> str:
        """Generate database name for user."""
        # Turso DB names can only contain lowercase letters, numbers, and dashes
        return f"user-{user_id}"

    def _get_db_url(self, db_name: str) -> str:
        """Generate Turso database URL."""
        return f"libsql://{db_name}-{self.turso_org_url}"

    def _get_local_replica_path(self, db_name: str) -> str:
        """Get path for local embedded replica."""
        return str(self.data_dir / f"{db_name}.db")

    def commit_and_sync(self, conn, user_id: str = None) -> None:
        """
        Commit changes and sync with remote if using embedded replicas.

        Args:
            conn: Database connection
            user_id: Optional user ID for logging
        """
        try:
            conn.commit()
            if self.embedded_replica:
                conn.sync()
                if user_id:
                    logger.debug("synced_after_commit", user_id=user_id)
        except Exception as e:
            logger.error("commit_sync_failed", user_id=user_id, error=str(e))
            raise

    @lru_cache(maxsize=100)
    def get_user_db(self, user_id: str):
        """
        Get or create database client for user.
        Uses LRU cache to maintain connections for most active users.

        Args:
            user_id: User's UUID

        Returns:
            Turso database connection
        """
        db_name = self._get_db_name(user_id)

        if db_name in self._connections:
            return self._connections[db_name]

        # Create new connection
        db_url = self._get_db_url(db_name)

        try:
            if self.embedded_replica:
                # Use embedded replica for local caching
                local_path = self._get_local_replica_path(db_name)
                conn = libsql.connect(
                    local_path,
                    sync_url=db_url,
                    auth_token=self.auth_token
                )
                # Sync with remote database
                conn.sync()
                logger.info("database_connected_with_replica", user_id=user_id, db_name=db_name)
            else:
                # Direct connection without replica
                conn = libsql.connect(
                    db_url,
                    auth_token=self.auth_token
                )
                logger.info("database_connected", user_id=user_id, db_name=db_name)

            # Store connection
            self._connections[db_name] = conn

            # Ensure schema is up to date
            self._ensure_schema(conn, user_id)

            return conn

        except Exception as e:
            logger.error("database_connection_failed", user_id=user_id, error=str(e))
            raise

    async def create_user_database(self, user_id: str) -> bool:
        """
        Create a new database for a user via Turso API.

        Args:
            user_id: User's UUID

        Returns:
            True if created successfully
        """
        db_name = self._get_db_name(user_id)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"https://api.turso.tech/v1/organizations/{self.turso_org_url.split('.')[0]}/databases",
                    headers={
                        "Authorization": f"Bearer {self.auth_token}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "name": db_name,
                        "group": "default"
                    },
                    timeout=30.0
                )

                if response.status_code in (200, 201):
                    logger.info("database_created", user_id=user_id, db_name=db_name)

                    # Initialize schema
                    db = self.get_user_db(user_id)
                    self._ensure_schema(db, user_id)

                    return True
                elif response.status_code == 409:
                    # Database already exists
                    logger.info("database_already_exists", user_id=user_id, db_name=db_name)
                    return True
                else:
                    logger.error(
                        "database_creation_failed",
                        user_id=user_id,
                        status=response.status_code,
                        response=response.text
                    )
                    return False

        except Exception as e:
            logger.error("database_creation_error", user_id=user_id, error=str(e))
            raise

    async def create_database_token(self, user_id: str, expiration: str = "never") -> Optional[str]:
        """
        Create an auth token for the user's database.

        Args:
            user_id: User's UUID
            expiration: "never" or duration string (e.g. "1d")

        Returns:
            JWT token string or None if failed
        """
        db_name = self._get_db_name(user_id)

        try:
            async with httpx.AsyncClient() as client:
                url = f"https://api.turso.tech/v1/organizations/{self.turso_org_url.split('.')[0]}/databases/{db_name}/auth/tokens"
                if expiration != "never":
                    url += f"?expiration={expiration}"

                # Retry loop
                max_retries = 3
                for attempt in range(max_retries):
                    response = await client.post(
                        url,
                        headers={
                            "Authorization": f"Bearer {self.auth_token}",
                        },
                        timeout=10.0
                    )
                    
                    if response.status_code == 200:
                        break # Success
                        
                    if response.status_code == 404 and attempt < max_retries - 1:
                        # Database might not be ready yet
                        logger.warning("token_creation_retry", attempt=attempt+1, user_id=user_id, url=url)
                        await asyncio.sleep(2.0)
                        continue
                    
                    # Stop if other error or max retries
                    break

                if response.status_code == 200:
                    data = response.json()
                    token = data.get("jwt")
                    logger.info("token_created", user_id=user_id, db_name=db_name)
                    return token
                else:
                    logger.error(
                        "token_creation_failed",
                        user_id=user_id,
                        status=response.status_code,
                        url=url,
                        response=response.text
                    )
                    return None

        except Exception as e:
            logger.error("token_creation_error", user_id=user_id, error=str(e))
            raise

    def _ensure_schema(self, conn, user_id: str) -> None:
        """
        Ensure database has correct schema version.
        Runs migrations if needed.

        Args:
            conn: Database connection
            user_id: User ID for logging
        """
        try:
            # Check if schema_version table exists
            result = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
            )

            rows = result.fetchall()

            if not rows:
                # No schema yet, run initial migration
                logger.info("initializing_schema", user_id=user_id)
                self._run_migration_v001(conn)
            else:
                # Check current version
                result = conn.execute(
                    "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
                )

                version_rows = result.fetchall()

                current_version = version_rows[0][0] if version_rows else 0
                logger.info("schema_version_check", user_id=user_id, version=current_version)

                # Run any pending migrations
                if current_version < 1:
                    self._run_migration_v001(conn)

        except Exception as e:
            logger.error("schema_check_failed", user_id=user_id, error=str(e))
            raise

    def _run_migration_v001(self, conn) -> None:
        """Run initial schema migration."""
        migration_sql = """
        -- Schema version tracking
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at INTEGER NOT NULL
        );

        -- Device information
        CREATE TABLE IF NOT EXISTS device_info (
            device_id TEXT PRIMARY KEY,
            device_name TEXT,
            device_type TEXT,
            platform TEXT,
            public_key TEXT NOT NULL,
            last_sync_at INTEGER,
            created_at INTEGER NOT NULL
        );

        -- Synced entries (encrypted)
        CREATE TABLE IF NOT EXISTS synced_entries (
            id TEXT PRIMARY KEY,
            device_id TEXT NOT NULL,
            encrypted_data BLOB NOT NULL,
            version INTEGER NOT NULL,
            vector_clock TEXT,
            is_deleted INTEGER DEFAULT 0,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            FOREIGN KEY (device_id) REFERENCES device_info(device_id)
        );
        CREATE INDEX IF NOT EXISTS idx_entries_updated ON synced_entries(updated_at);
        CREATE INDEX IF NOT EXISTS idx_entries_deleted ON synced_entries(is_deleted, updated_at);

        -- Synced memories (encrypted)
        CREATE TABLE IF NOT EXISTS synced_memories (
            id TEXT PRIMARY KEY,
            encrypted_data BLOB NOT NULL,
            version INTEGER NOT NULL,
            is_deleted INTEGER DEFAULT 0,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_memories_updated ON synced_memories(updated_at);

        -- Synced tags (encrypted)
        CREATE TABLE IF NOT EXISTS synced_tags (
            id TEXT PRIMARY KEY,
            entry_id TEXT NOT NULL,
            encrypted_data BLOB NOT NULL,
            version INTEGER NOT NULL,
            is_deleted INTEGER DEFAULT 0,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_tags_entry ON synced_tags(entry_id);
        CREATE INDEX IF NOT EXISTS idx_tags_updated ON synced_tags(updated_at);

        -- LLM usage tracking
        CREATE TABLE IF NOT EXISTS llm_usage (
            id TEXT PRIMARY KEY,
            model TEXT NOT NULL,
            input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            cost_usd REAL,
            created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_usage_date ON llm_usage(created_at);

        -- Record migration
        INSERT INTO schema_version (version, applied_at)
        VALUES (1, strftime('%s', 'now'));
        """

        self._execute_sql_script(conn, migration_sql)
        logger.info("migration_v001_completed")

    @staticmethod
    def _execute_sql_script(conn, sql: str) -> None:
        """
        Execute a SQL script containing multiple statements.

        libsql/Hrana requires one statement per execute call.
        """
        statements = [s.strip() for s in sql.strip().split(";") if s.strip()]
        for statement in statements:
            conn.execute(statement)

    async def list_all_user_databases(self) -> List[str]:
        """
        List all user databases from Turso API.

        Returns:
            List of database names
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://api.turso.tech/v1/organizations/{self.turso_org_url.split('.')[0]}/databases",
                    headers={
                        "Authorization": f"Bearer {self.auth_token}"
                    },
                    timeout=30.0
                )

                if response.status_code == 200:
                    databases = response.json().get("databases", [])
                    user_dbs = [
                        db["name"] for db in databases
                        if db["name"].startswith("user_")
                    ]
                    logger.info("listed_databases", count=len(user_dbs))
                    return user_dbs
                else:
                    logger.error("list_databases_failed", status=response.status_code)
                    return []

        except Exception as e:
            logger.error("list_databases_error", error=str(e))
            return []

    def cleanup_inactive_replicas(self, days: int = 7) -> None:
        """
        Clean up local embedded replicas for inactive users.

        Args:
            days: Remove replicas not accessed in this many days
        """
        if not self.embedded_replica:
            return

        import time
        cutoff_time = time.time() - (days * 86400)

        for db_file in self.data_dir.glob("user_*.db"):
            if db_file.stat().st_atime < cutoff_time:
                try:
                    db_file.unlink()
                    logger.info("cleaned_up_replica", file=db_file.name)
                except Exception as e:
                    logger.error("cleanup_failed", file=db_file.name, error=str(e))

    def close_all_connections(self) -> None:
        """Close all database connections."""
        for db_name, conn in self._connections.items():
            try:
                conn.close()
                logger.info("connection_closed", db_name=db_name)
            except Exception as e:
                logger.error("connection_close_failed", db_name=db_name, error=str(e))

        self._connections.clear()


# Global database manager instance
db_manager = TursoDatabaseManager()


def get_db_manager() -> TursoDatabaseManager:
    """Dependency injection for database manager."""
    return db_manager
