"""
Pydantic models for sync service.
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


# ========== Sync Item Models ==========

class SyncEntry(BaseModel):
    """
    Encrypted journal entry for sync.

    Includes vector clock for conflict resolution across devices.
    """
    id: str
    device_id: str
    encrypted_data: bytes
    version: int
    vector_clock: Optional[Dict[str, int]] = None  # {device_id: version}
    is_deleted: bool = False
    created_at: int
    updated_at: int

    class Config:
        json_schema_extra = {
            "example": {
                "id": "entry-123",
                "device_id": "device-abc",
                "encrypted_data": "base64_encoded_encrypted_blob",
                "version": 5,
                "vector_clock": {"device-abc": 5, "device-xyz": 3},
                "is_deleted": False,
                "created_at": 1704067200,
                "updated_at": 1704153600
            }
        }


class SyncMemory(BaseModel):
    """
    Encrypted memory (knowledge graph node) for sync.

    Uses timestamp-based sync (no vector clock).
    """
    id: str
    encrypted_data: bytes
    version: int
    is_deleted: bool = False
    created_at: int
    updated_at: int

    class Config:
        json_schema_extra = {
            "example": {
                "id": "memory-456",
                "encrypted_data": "base64_encoded_encrypted_blob",
                "version": 2,
                "is_deleted": False,
                "created_at": 1704067200,
                "updated_at": 1704153600
            }
        }


class SyncTag(BaseModel):
    """
    Encrypted tag for sync.

    Links to an entry. Uses timestamp-based sync.
    """
    id: str
    entry_id: str
    encrypted_data: bytes
    version: int
    is_deleted: bool = False
    created_at: int
    updated_at: int

    class Config:
        json_schema_extra = {
            "example": {
                "id": "tag-789",
                "entry_id": "entry-123",
                "encrypted_data": "base64_encoded_encrypted_blob",
                "version": 1,
                "is_deleted": False,
                "created_at": 1704067200,
                "updated_at": 1704153600
            }
        }


# ========== Sync Request/Response Models ==========

class SyncPushRequest(BaseModel):
    """
    Client pushes local changes to server.
    """
    entries: List[SyncEntry] = Field(default_factory=list)
    memories: List[SyncMemory] = Field(default_factory=list)
    tags: List[SyncTag] = Field(default_factory=list)

    # Client's last known sync state
    last_sync_at: Optional[int] = None

    class Config:
        json_schema_extra = {
            "example": {
                "entries": [
                    {
                        "id": "entry-123",
                        "device_id": "device-abc",
                        "encrypted_data": "base64_blob",
                        "version": 5,
                        "vector_clock": {"device-abc": 5},
                        "is_deleted": False,
                        "created_at": 1704067200,
                        "updated_at": 1704153600
                    }
                ],
                "memories": [],
                "tags": [],
                "last_sync_at": 1704067200
            }
        }


class ConflictItem(BaseModel):
    """
    Represents a conflict between client and server versions.
    """
    item_type: str  # "entry", "memory", or "tag"
    item_id: str
    server_version: Dict[str, Any]  # Server's version of the item
    client_version: Dict[str, Any]  # Client's version (from push)
    conflict_reason: str  # e.g., "concurrent_modification", "vector_clock_conflict"


class SyncPushResponse(BaseModel):
    """
    Server response after push operation.
    """
    accepted_entries: int
    accepted_memories: int
    accepted_tags: int
    conflicts: List[ConflictItem] = Field(default_factory=list)
    server_time: int  # Server's current timestamp

    class Config:
        json_schema_extra = {
            "example": {
                "accepted_entries": 5,
                "accepted_memories": 2,
                "accepted_tags": 3,
                "conflicts": [],
                "server_time": 1704153600
            }
        }


class SyncPullRequest(BaseModel):
    """
    Client requests changes from server since last sync.
    """
    last_sync_at: int = Field(..., description="Unix timestamp of last successful sync")
    device_id: str = Field(..., description="Current device ID for vector clock filtering")

    class Config:
        json_schema_extra = {
            "example": {
                "last_sync_at": 1704067200,
                "device_id": "device-abc"
            }
        }


class SyncPullResponse(BaseModel):
    """
    Server returns all changes since last sync.
    """
    entries: List[SyncEntry] = Field(default_factory=list)
    memories: List[SyncMemory] = Field(default_factory=list)
    tags: List[SyncTag] = Field(default_factory=list)
    server_time: int  # Server's current timestamp
    has_more: bool = False  # Pagination flag for future use

    class Config:
        json_schema_extra = {
            "example": {
                "entries": [
                    {
                        "id": "entry-456",
                        "device_id": "device-xyz",
                        "encrypted_data": "base64_blob",
                        "version": 3,
                        "vector_clock": {"device-xyz": 3},
                        "is_deleted": False,
                        "created_at": 1704067200,
                        "updated_at": 1704153600
                    }
                ],
                "memories": [],
                "tags": [],
                "server_time": 1704153600,
                "has_more": False
            }
        }


class SyncStatusResponse(BaseModel):
    """
    Sync status for current user.
    """
    user_id: str
    total_entries: int
    total_memories: int
    total_tags: int
    last_sync_at: Optional[int] = None
    device_count: int
    sync_enabled: bool

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "user-uuid",
                "total_entries": 150,
                "total_memories": 45,
                "total_tags": 89,
                "last_sync_at": 1704153600,
                "device_count": 3,
                "sync_enabled": True
            }
        }
