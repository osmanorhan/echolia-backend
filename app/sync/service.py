"""
Sync service business logic.

Handles push/pull operations with conflict detection and resolution.
"""
import json
import time
import structlog
from typing import List, Tuple, Dict, Any, Optional
from base64 import b64encode, b64decode

from app.database import TursoDatabaseManager
from app.master_db import MasterDatabaseManager
from app.sync.models import (
    SyncEntry,
    SyncMemory,
    SyncTag,
    SyncPushRequest,
    SyncPushResponse,
    SyncPullRequest,
    SyncPullResponse,
    SyncStatusResponse,
    ConflictItem,
)


logger = structlog.get_logger()


class SyncService:
    """
    Sync service for managing encrypted data synchronization.

    Features:
    - Vector clock-based conflict detection for entries
    - Timestamp-based sync for memories and tags
    - Soft deletes (tombstones)
    - Multi-device support
    """

    def __init__(
        self,
        db_manager: TursoDatabaseManager,
        master_db_manager: MasterDatabaseManager,
    ):
        self.db_manager = db_manager
        self.master_db_manager = master_db_manager

    # ========== Vector Clock Helpers ==========

    def _parse_vector_clock(self, vector_clock_str: Optional[str]) -> Dict[str, int]:
        """Parse vector clock JSON string to dict."""
        if not vector_clock_str:
            return {}
        try:
            return json.loads(vector_clock_str)
        except (json.JSONDecodeError, TypeError):
            return {}

    def _serialize_vector_clock(self, vector_clock: Optional[Dict[str, int]]) -> str:
        """Serialize vector clock dict to JSON string."""
        if not vector_clock:
            return "{}"
        return json.dumps(vector_clock)

    def _compare_vector_clocks(
        self, vc1: Dict[str, int], vc2: Dict[str, int]
    ) -> str:
        """
        Compare two vector clocks.

        Returns:
            "greater": vc1 > vc2 (vc1 happened after vc2)
            "less": vc1 < vc2 (vc1 happened before vc2)
            "equal": vc1 == vc2
            "concurrent": vc1 and vc2 are concurrent (conflict)
        """
        if vc1 == vc2:
            return "equal"

        vc1_greater = False
        vc2_greater = False

        # Get all device IDs from both clocks
        all_devices = set(vc1.keys()) | set(vc2.keys())

        for device_id in all_devices:
            v1 = vc1.get(device_id, 0)
            v2 = vc2.get(device_id, 0)

            if v1 > v2:
                vc1_greater = True
            elif v1 < v2:
                vc2_greater = True

        if vc1_greater and not vc2_greater:
            return "greater"
        elif vc2_greater and not vc1_greater:
            return "less"
        else:
            return "concurrent"

    def _merge_vector_clocks(
        self, vc1: Dict[str, int], vc2: Dict[str, int]
    ) -> Dict[str, int]:
        """Merge two vector clocks by taking max for each device."""
        merged = {}
        all_devices = set(vc1.keys()) | set(vc2.keys())

        for device_id in all_devices:
            merged[device_id] = max(vc1.get(device_id, 0), vc2.get(device_id, 0))

        return merged

    # ========== Push Operation ==========

    def push(
        self, user_id: str, device_id: str, request: SyncPushRequest
    ) -> SyncPushResponse:
        """
        Push local changes from client to server.

        Args:
            user_id: User UUID
            device_id: Device ID making the push
            request: SyncPushRequest with changes

        Returns:
            SyncPushResponse with accepted counts and conflicts
        """
        db = self.db_manager.get_user_db(user_id)
        conflicts: List[ConflictItem] = []

        accepted_entries = 0
        accepted_memories = 0
        accepted_tags = 0

        # Process entries (with vector clock conflict detection)
        for entry in request.entries:
            conflict = self._push_entry(db, user_id, device_id, entry)
            if conflict:
                conflicts.append(conflict)
            else:
                accepted_entries += 1

        # Process memories (timestamp-based, last-write-wins)
        for memory in request.memories:
            conflict = self._push_memory(db, user_id, memory)
            if conflict:
                conflicts.append(conflict)
            else:
                accepted_memories += 1

        # Process tags (timestamp-based, last-write-wins)
        for tag in request.tags:
            conflict = self._push_tag(db, user_id, tag)
            if conflict:
                conflicts.append(conflict)
            else:
                accepted_tags += 1

        # Commit and sync
        self.db_manager.commit_and_sync(db, user_id)

        logger.info(
            "sync_push_completed",
            user_id=user_id,
            device_id=device_id,
            accepted_entries=accepted_entries,
            accepted_memories=accepted_memories,
            accepted_tags=accepted_tags,
            conflicts_count=len(conflicts),
        )

        return SyncPushResponse(
            accepted_entries=accepted_entries,
            accepted_memories=accepted_memories,
            accepted_tags=accepted_tags,
            conflicts=conflicts,
            server_time=int(time.time()),
        )

    def _push_entry(
        self, db, user_id: str, device_id: str, entry: SyncEntry
    ) -> Optional[ConflictItem]:
        """
        Push a single entry with vector clock conflict detection.

        Returns:
            ConflictItem if conflict detected, None otherwise
        """
        try:
            # Check if entry exists on server
            result = db.execute(
                "SELECT encrypted_data, version, vector_clock, is_deleted, created_at, updated_at FROM synced_entries WHERE id = ?",
                [entry.id],
            )

            client_vc = entry.vector_clock or {}
            client_vc_str = self._serialize_vector_clock(client_vc)

            if not result.rows:
                # New entry, insert it
                db.execute(
                    """
                    INSERT INTO synced_entries (id, device_id, encrypted_data, version, vector_clock, is_deleted, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        entry.id,
                        entry.device_id,
                        entry.encrypted_data,
                        entry.version,
                        client_vc_str,
                        1 if entry.is_deleted else 0,
                        entry.created_at,
                        entry.updated_at,
                    ],
                )
                logger.debug("entry_inserted", entry_id=entry.id, user_id=user_id)
                return None

            # Entry exists, check for conflicts
            row = result.rows[0]
            server_encrypted_data = row[0]
            server_version = row[1]
            server_vc_str = row[2]
            server_is_deleted = bool(row[3])
            server_created_at = row[4]
            server_updated_at = row[5]

            server_vc = self._parse_vector_clock(server_vc_str)

            # Compare vector clocks
            comparison = self._compare_vector_clocks(client_vc, server_vc)

            if comparison == "greater":
                # Client version is newer, update server
                merged_vc = client_vc  # Client's clock already includes server's updates
                merged_vc_str = self._serialize_vector_clock(merged_vc)

                db.execute(
                    """
                    UPDATE synced_entries
                    SET device_id = ?, encrypted_data = ?, version = ?, vector_clock = ?, is_deleted = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    [
                        entry.device_id,
                        entry.encrypted_data,
                        entry.version,
                        merged_vc_str,
                        1 if entry.is_deleted else 0,
                        entry.updated_at,
                        entry.id,
                    ],
                )
                logger.debug("entry_updated", entry_id=entry.id, user_id=user_id)
                return None

            elif comparison == "less":
                # Server version is newer, reject client's push
                logger.debug(
                    "entry_rejected_server_newer",
                    entry_id=entry.id,
                    user_id=user_id,
                )
                return ConflictItem(
                    item_type="entry",
                    item_id=entry.id,
                    server_version={
                        "encrypted_data": b64encode(server_encrypted_data).decode(),
                        "version": server_version,
                        "vector_clock": server_vc,
                        "is_deleted": server_is_deleted,
                        "created_at": server_created_at,
                        "updated_at": server_updated_at,
                    },
                    client_version={
                        "encrypted_data": b64encode(entry.encrypted_data).decode()
                        if isinstance(entry.encrypted_data, bytes)
                        else entry.encrypted_data,
                        "version": entry.version,
                        "vector_clock": client_vc,
                        "is_deleted": entry.is_deleted,
                        "created_at": entry.created_at,
                        "updated_at": entry.updated_at,
                    },
                    conflict_reason="server_version_newer",
                )

            elif comparison == "equal":
                # Same version, no update needed
                logger.debug("entry_unchanged", entry_id=entry.id, user_id=user_id)
                return None

            else:  # concurrent
                # Concurrent modification detected - conflict!
                logger.warning(
                    "entry_conflict_concurrent",
                    entry_id=entry.id,
                    user_id=user_id,
                    client_vc=client_vc,
                    server_vc=server_vc,
                )

                # Merge vector clocks for conflict resolution
                merged_vc = self._merge_vector_clocks(client_vc, server_vc)
                merged_vc_str = self._serialize_vector_clock(merged_vc)

                # Use timestamp to break tie (last-write-wins as fallback)
                if entry.updated_at >= server_updated_at:
                    # Client wins
                    db.execute(
                        """
                        UPDATE synced_entries
                        SET device_id = ?, encrypted_data = ?, version = ?, vector_clock = ?, is_deleted = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        [
                            entry.device_id,
                            entry.encrypted_data,
                            entry.version,
                            merged_vc_str,
                            1 if entry.is_deleted else 0,
                            entry.updated_at,
                            entry.id,
                        ],
                    )
                    logger.debug(
                        "entry_conflict_resolved_client_wins",
                        entry_id=entry.id,
                        user_id=user_id,
                    )
                    return None
                else:
                    # Server wins, but still report conflict
                    return ConflictItem(
                        item_type="entry",
                        item_id=entry.id,
                        server_version={
                            "encrypted_data": b64encode(server_encrypted_data).decode(),
                            "version": server_version,
                            "vector_clock": server_vc,
                            "is_deleted": server_is_deleted,
                            "created_at": server_created_at,
                            "updated_at": server_updated_at,
                        },
                        client_version={
                            "encrypted_data": b64encode(entry.encrypted_data).decode()
                            if isinstance(entry.encrypted_data, bytes)
                            else entry.encrypted_data,
                            "version": entry.version,
                            "vector_clock": client_vc,
                            "is_deleted": entry.is_deleted,
                            "created_at": entry.created_at,
                            "updated_at": entry.updated_at,
                        },
                        conflict_reason="concurrent_modification",
                    )

        except Exception as e:
            logger.error(
                "entry_push_failed", entry_id=entry.id, user_id=user_id, error=str(e)
            )
            raise

    def _push_memory(
        self, db, user_id: str, memory: SyncMemory
    ) -> Optional[ConflictItem]:
        """
        Push a single memory (timestamp-based, last-write-wins).

        Returns:
            ConflictItem if conflict detected, None otherwise
        """
        try:
            # Check if memory exists on server
            result = db.execute(
                "SELECT encrypted_data, version, is_deleted, created_at, updated_at FROM synced_memories WHERE id = ?",
                [memory.id],
            )

            if not result.rows:
                # New memory, insert it
                db.execute(
                    """
                    INSERT INTO synced_memories (id, encrypted_data, version, is_deleted, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        memory.id,
                        memory.encrypted_data,
                        memory.version,
                        1 if memory.is_deleted else 0,
                        memory.created_at,
                        memory.updated_at,
                    ],
                )
                logger.debug("memory_inserted", memory_id=memory.id, user_id=user_id)
                return None

            # Memory exists, check timestamps
            row = result.rows[0]
            server_updated_at = row[4]

            if memory.updated_at > server_updated_at:
                # Client version is newer, update server
                db.execute(
                    """
                    UPDATE synced_memories
                    SET encrypted_data = ?, version = ?, is_deleted = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    [
                        memory.encrypted_data,
                        memory.version,
                        1 if memory.is_deleted else 0,
                        memory.updated_at,
                        memory.id,
                    ],
                )
                logger.debug("memory_updated", memory_id=memory.id, user_id=user_id)
                return None
            elif memory.updated_at < server_updated_at:
                # Server version is newer, reject
                logger.debug(
                    "memory_rejected_server_newer",
                    memory_id=memory.id,
                    user_id=user_id,
                )
                return ConflictItem(
                    item_type="memory",
                    item_id=memory.id,
                    server_version={
                        "encrypted_data": b64encode(row[0]).decode(),
                        "version": row[1],
                        "is_deleted": bool(row[2]),
                        "created_at": row[3],
                        "updated_at": row[4],
                    },
                    client_version={
                        "encrypted_data": b64encode(memory.encrypted_data).decode()
                        if isinstance(memory.encrypted_data, bytes)
                        else memory.encrypted_data,
                        "version": memory.version,
                        "is_deleted": memory.is_deleted,
                        "created_at": memory.created_at,
                        "updated_at": memory.updated_at,
                    },
                    conflict_reason="server_version_newer",
                )
            else:
                # Same timestamp, no update needed
                logger.debug("memory_unchanged", memory_id=memory.id, user_id=user_id)
                return None

        except Exception as e:
            logger.error(
                "memory_push_failed",
                memory_id=memory.id,
                user_id=user_id,
                error=str(e),
            )
            raise

    def _push_tag(self, db, user_id: str, tag: SyncTag) -> Optional[ConflictItem]:
        """
        Push a single tag (timestamp-based, last-write-wins).

        Returns:
            ConflictItem if conflict detected, None otherwise
        """
        try:
            # Check if tag exists on server
            result = db.execute(
                "SELECT entry_id, encrypted_data, version, is_deleted, created_at, updated_at FROM synced_tags WHERE id = ?",
                [tag.id],
            )

            if not result.rows:
                # New tag, insert it
                db.execute(
                    """
                    INSERT INTO synced_tags (id, entry_id, encrypted_data, version, is_deleted, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        tag.id,
                        tag.entry_id,
                        tag.encrypted_data,
                        tag.version,
                        1 if tag.is_deleted else 0,
                        tag.created_at,
                        tag.updated_at,
                    ],
                )
                logger.debug("tag_inserted", tag_id=tag.id, user_id=user_id)
                return None

            # Tag exists, check timestamps
            row = result.rows[0]
            server_updated_at = row[5]

            if tag.updated_at > server_updated_at:
                # Client version is newer, update server
                db.execute(
                    """
                    UPDATE synced_tags
                    SET entry_id = ?, encrypted_data = ?, version = ?, is_deleted = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    [
                        tag.entry_id,
                        tag.encrypted_data,
                        tag.version,
                        1 if tag.is_deleted else 0,
                        tag.updated_at,
                        tag.id,
                    ],
                )
                logger.debug("tag_updated", tag_id=tag.id, user_id=user_id)
                return None
            elif tag.updated_at < server_updated_at:
                # Server version is newer, reject
                logger.debug(
                    "tag_rejected_server_newer", tag_id=tag.id, user_id=user_id
                )
                return ConflictItem(
                    item_type="tag",
                    item_id=tag.id,
                    server_version={
                        "entry_id": row[0],
                        "encrypted_data": b64encode(row[1]).decode(),
                        "version": row[2],
                        "is_deleted": bool(row[3]),
                        "created_at": row[4],
                        "updated_at": row[5],
                    },
                    client_version={
                        "entry_id": tag.entry_id,
                        "encrypted_data": b64encode(tag.encrypted_data).decode()
                        if isinstance(tag.encrypted_data, bytes)
                        else tag.encrypted_data,
                        "version": tag.version,
                        "is_deleted": tag.is_deleted,
                        "created_at": tag.created_at,
                        "updated_at": tag.updated_at,
                    },
                    conflict_reason="server_version_newer",
                )
            else:
                # Same timestamp, no update needed
                logger.debug("tag_unchanged", tag_id=tag.id, user_id=user_id)
                return None

        except Exception as e:
            logger.error(
                "tag_push_failed", tag_id=tag.id, user_id=user_id, error=str(e)
            )
            raise

    # ========== Pull Operation ==========

    def pull(
        self, user_id: str, device_id: str, request: SyncPullRequest
    ) -> SyncPullResponse:
        """
        Pull changes from server since last sync.

        Args:
            user_id: User UUID
            device_id: Device ID requesting pull
            request: SyncPullRequest with last sync timestamp

        Returns:
            SyncPullResponse with all changes since last_sync_at
        """
        db = self.db_manager.get_user_db(user_id)

        # Get entries updated since last sync
        entries = self._pull_entries(db, user_id, request.last_sync_at)

        # Get memories updated since last sync
        memories = self._pull_memories(db, user_id, request.last_sync_at)

        # Get tags updated since last sync
        tags = self._pull_tags(db, user_id, request.last_sync_at)

        logger.info(
            "sync_pull_completed",
            user_id=user_id,
            device_id=device_id,
            entries_count=len(entries),
            memories_count=len(memories),
            tags_count=len(tags),
            since=request.last_sync_at,
        )

        return SyncPullResponse(
            entries=entries,
            memories=memories,
            tags=tags,
            server_time=int(time.time()),
            has_more=False,
        )

    def _pull_entries(
        self, db, user_id: str, last_sync_at: int
    ) -> List[SyncEntry]:
        """Pull all entries updated since last_sync_at."""
        try:
            result = db.execute(
                """
                SELECT id, device_id, encrypted_data, version, vector_clock, is_deleted, created_at, updated_at
                FROM synced_entries
                WHERE updated_at > ?
                ORDER BY updated_at ASC
                """,
                [last_sync_at],
            )

            entries = []
            for row in result.rows:
                vector_clock = self._parse_vector_clock(row[4])
                entries.append(
                    SyncEntry(
                        id=row[0],
                        device_id=row[1],
                        encrypted_data=row[2],
                        version=row[3],
                        vector_clock=vector_clock,
                        is_deleted=bool(row[5]),
                        created_at=row[6],
                        updated_at=row[7],
                    )
                )

            logger.debug(
                "entries_pulled", user_id=user_id, count=len(entries)
            )
            return entries

        except Exception as e:
            logger.error("entries_pull_failed", user_id=user_id, error=str(e))
            raise

    def _pull_memories(
        self, db, user_id: str, last_sync_at: int
    ) -> List[SyncMemory]:
        """Pull all memories updated since last_sync_at."""
        try:
            result = db.execute(
                """
                SELECT id, encrypted_data, version, is_deleted, created_at, updated_at
                FROM synced_memories
                WHERE updated_at > ?
                ORDER BY updated_at ASC
                """,
                [last_sync_at],
            )

            memories = []
            for row in result.rows:
                memories.append(
                    SyncMemory(
                        id=row[0],
                        encrypted_data=row[1],
                        version=row[2],
                        is_deleted=bool(row[3]),
                        created_at=row[4],
                        updated_at=row[5],
                    )
                )

            logger.debug(
                "memories_pulled", user_id=user_id, count=len(memories)
            )
            return memories

        except Exception as e:
            logger.error("memories_pull_failed", user_id=user_id, error=str(e))
            raise

    def _pull_tags(self, db, user_id: str, last_sync_at: int) -> List[SyncTag]:
        """Pull all tags updated since last_sync_at."""
        try:
            result = db.execute(
                """
                SELECT id, entry_id, encrypted_data, version, is_deleted, created_at, updated_at
                FROM synced_tags
                WHERE updated_at > ?
                ORDER BY updated_at ASC
                """,
                [last_sync_at],
            )

            tags = []
            for row in result.rows:
                tags.append(
                    SyncTag(
                        id=row[0],
                        entry_id=row[1],
                        encrypted_data=row[2],
                        version=row[3],
                        is_deleted=bool(row[4]),
                        created_at=row[5],
                        updated_at=row[6],
                    )
                )

            logger.debug("tags_pulled", user_id=user_id, count=len(tags))
            return tags

        except Exception as e:
            logger.error("tags_pull_failed", user_id=user_id, error=str(e))
            raise

    # ========== Status Operation ==========

    def get_status(self, user_id: str) -> SyncStatusResponse:
        """
        Get sync status for user.

        Args:
            user_id: User UUID

        Returns:
            SyncStatusResponse with sync statistics
        """
        db = self.db_manager.get_user_db(user_id)

        # Count total entries (excluding deleted)
        result = db.execute(
            "SELECT COUNT(*) FROM synced_entries WHERE is_deleted = 0"
        )
        total_entries = result.rows[0][0] if result.rows else 0

        # Count total memories (excluding deleted)
        result = db.execute(
            "SELECT COUNT(*) FROM synced_memories WHERE is_deleted = 0"
        )
        total_memories = result.rows[0][0] if result.rows else 0

        # Count total tags (excluding deleted)
        result = db.execute(
            "SELECT COUNT(*) FROM synced_tags WHERE is_deleted = 0"
        )
        total_tags = result.rows[0][0] if result.rows else 0

        # Get last sync timestamp (max updated_at from all tables)
        last_sync_at = None
        result = db.execute(
            """
            SELECT MAX(updated_at) FROM (
                SELECT MAX(updated_at) as updated_at FROM synced_entries
                UNION ALL
                SELECT MAX(updated_at) as updated_at FROM synced_memories
                UNION ALL
                SELECT MAX(updated_at) as updated_at FROM synced_tags
            )
            """
        )
        if result.rows and result.rows[0][0]:
            last_sync_at = result.rows[0][0]

        # Get device count from master database
        devices = self.master_db_manager.get_user_devices(user_id)
        device_count = len(devices)

        # Check if sync add-on is active
        sync_enabled = self.master_db_manager.is_add_on_active(user_id, "sync")

        logger.info(
            "sync_status_retrieved",
            user_id=user_id,
            total_entries=total_entries,
            total_memories=total_memories,
            total_tags=total_tags,
            sync_enabled=sync_enabled,
        )

        return SyncStatusResponse(
            user_id=user_id,
            total_entries=total_entries,
            total_memories=total_memories,
            total_tags=total_tags,
            last_sync_at=last_sync_at,
            device_count=device_count,
            sync_enabled=sync_enabled,
        )
