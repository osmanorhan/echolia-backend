"""
Sync API routes.
"""
from typing import Tuple
from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.dependencies import get_current_user
from app.database import db_manager
from app.master_db import master_db_manager
from app.sync.service import SyncService
from app.sync.models import (
    SyncPushRequest,
    SyncPushResponse,
    SyncPullRequest,
    SyncPullResponse,
    SyncStatusResponse,
)


router = APIRouter(prefix="/sync", tags=["sync"])


def get_sync_service() -> SyncService:
    """Dependency: Get SyncService instance."""
    return SyncService(db_manager, master_db_manager)


@router.post("/push", response_model=SyncPushResponse)
async def push_changes(
    request: SyncPushRequest,
    current_user: Tuple[str, str] = Depends(get_current_user),
    sync_service: SyncService = Depends(get_sync_service),
):
    """
    Push local changes to server.

    Requires sync add-on to be active.

    **Request Body:**
    - `entries`: List of encrypted entries with vector clocks
    - `memories`: List of encrypted memories
    - `tags`: List of encrypted tags
    - `last_sync_at`: Client's last known sync timestamp

    **Response:**
    - `accepted_entries`: Number of entries accepted
    - `accepted_memories`: Number of memories accepted
    - `accepted_tags`: Number of tags accepted
    - `conflicts`: List of conflicts detected (client should resolve)
    - `server_time`: Server's current timestamp

    **Conflict Resolution:**
    - For entries: Vector clock comparison detects concurrent modifications
    - For memories/tags: Timestamp-based (last-write-wins)
    - Client should pull server versions and re-push with merged data
    """
    user_id, device_id = current_user

    # Check if sync add-on is active
    if not master_db_manager.is_add_on_active(user_id, "sync"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sync add-on required. Please subscribe to enable cross-device sync.",
        )

    try:
        response = sync_service.push(user_id, device_id, request)
        return response
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Sync push failed: {str(e)}",
        )


@router.post("/pull", response_model=SyncPullResponse)
async def pull_changes(
    request: SyncPullRequest,
    current_user: Tuple[str, str] = Depends(get_current_user),
    sync_service: SyncService = Depends(get_sync_service),
):
    """
    Pull changes from server since last sync.

    Requires sync add-on to be active.

    **Request Body:**
    - `last_sync_at`: Unix timestamp of last successful sync
    - `device_id`: Current device ID

    **Response:**
    - `entries`: List of entries updated since last_sync_at
    - `memories`: List of memories updated since last_sync_at
    - `tags`: List of tags updated since last_sync_at
    - `server_time`: Server's current timestamp
    - `has_more`: Pagination flag (future use)

    **Usage:**
    1. Client sends last known sync timestamp
    2. Server returns all changes since that time
    3. Client merges changes locally (respecting vector clocks)
    4. Client updates last_sync_at to server_time
    """
    user_id, device_id = current_user

    # Check if sync add-on is active
    if not master_db_manager.is_add_on_active(user_id, "sync"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sync add-on required. Please subscribe to enable cross-device sync.",
        )

    try:
        response = sync_service.pull(user_id, device_id, request)
        return response
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Sync pull failed: {str(e)}",
        )


@router.get("/status", response_model=SyncStatusResponse)
async def get_sync_status(
    current_user: Tuple[str, str] = Depends(get_current_user),
    sync_service: SyncService = Depends(get_sync_service),
):
    """
    Get sync status for current user.

    **Response:**
    - `user_id`: User UUID
    - `total_entries`: Total entries in user's database
    - `total_memories`: Total memories in user's database
    - `total_tags`: Total tags in user's database
    - `last_sync_at`: Timestamp of last sync operation
    - `device_count`: Number of registered devices
    - `sync_enabled`: Whether sync add-on is active

    **Usage:**
    - Check sync status before syncing
    - Display sync statistics in app UI
    - Monitor data growth
    """
    user_id, device_id = current_user

    try:
        response = sync_service.get_status(user_id)
        return response
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get sync status: {str(e)}",
        )
