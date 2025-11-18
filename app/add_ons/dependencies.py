"""
Add-ons dependencies for FastAPI route protection.

Provides reusable dependencies to enforce add-on requirements.
"""
from fastapi import Depends, HTTPException, status
from typing import Tuple
import structlog

from app.add_ons.models import AddOnType, FeatureFlags
from app.add_ons.service import AddOnsService
from app.auth.dependencies import get_current_user
from app.master_db import get_master_db_manager, MasterDatabaseManager


logger = structlog.get_logger()


def get_add_ons_service_dependency(
    master_db: MasterDatabaseManager = Depends(get_master_db_manager)
) -> AddOnsService:
    """Dependency to get add-ons service."""
    return AddOnsService(master_db)


# ========== Add-On Requirement Dependencies ==========

async def require_sync_addon(
    current_user: Tuple[str, str] = Depends(get_current_user),
    add_ons_service: AddOnsService = Depends(get_add_ons_service_dependency)
) -> None:
    """
    Dependency that requires active Sync add-on.

    Use this dependency on routes that require Sync add-on:

    ```python
    @router.post("/sync/push")
    async def sync_push(
        _: None = Depends(require_sync_addon),
        current_user: Tuple[str, str] = Depends(get_current_user)
    ):
        # Sync logic here
        pass
    ```

    Raises:
        HTTPException: 403 if user doesn't have active Sync add-on
    """
    user_id, _ = current_user

    if not add_ons_service.is_add_on_active(user_id, AddOnType.SYNC):
        logger.warning(
            "sync_addon_required",
            user_id=user_id,
            message="User attempted to access sync feature without active add-on"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sync add-on required. Please subscribe to Sync ($2/month) to use this feature."
        )


async def require_ai_addon(
    current_user: Tuple[str, str] = Depends(get_current_user),
    add_ons_service: AddOnsService = Depends(get_add_ons_service_dependency)
) -> None:
    """
    Dependency that requires active AI add-on.

    Note: This is primarily for future premium AI features.
    The /llm/generate endpoint has its own tier-based access control
    (free tier: 10/day, AI add-on: 5000/day).

    Use this dependency for routes that strictly require AI add-on:

    ```python
    @router.post("/llm/premium-feature")
    async def premium_feature(
        _: None = Depends(require_ai_addon),
        current_user: Tuple[str, str] = Depends(get_current_user)
    ):
        # Premium AI feature logic
        pass
    ```

    Raises:
        HTTPException: 403 if user doesn't have active AI add-on
    """
    user_id, _ = current_user

    if not add_ons_service.is_add_on_active(user_id, AddOnType.AI):
        logger.warning(
            "ai_addon_required",
            user_id=user_id,
            message="User attempted to access AI feature without active add-on"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="AI add-on required. Please subscribe to AI ($3/month) to use this feature."
        )


async def check_add_on(
    add_on_type: AddOnType,
    current_user: Tuple[str, str] = Depends(get_current_user),
    add_ons_service: AddOnsService = Depends(get_add_ons_service_dependency)
) -> bool:
    """
    Generic add-on checker (non-blocking).

    Unlike require_sync_addon and require_ai_addon, this dependency
    returns a boolean instead of raising an exception.

    Use this when you want to check add-on status without blocking:

    ```python
    @router.get("/some-endpoint")
    async def some_endpoint(
        has_sync: bool = Depends(lambda: check_add_on(AddOnType.SYNC)),
        current_user: Tuple[str, str] = Depends(get_current_user)
    ):
        if has_sync:
            # Show sync features
        else:
            # Show upgrade prompt
        pass
    ```

    Args:
        add_on_type: Type of add-on to check

    Returns:
        True if add-on is active
    """
    user_id, _ = current_user
    return add_ons_service.is_add_on_active(user_id, add_on_type)


async def get_user_feature_flags(
    current_user: Tuple[str, str] = Depends(get_current_user),
    add_ons_service: AddOnsService = Depends(get_add_ons_service_dependency)
) -> FeatureFlags:
    """
    Dependency to get user's feature flags.

    Returns FeatureFlags object with all boolean flags.
    Use this when you need to check multiple add-ons at once:

    ```python
    @router.get("/dashboard")
    async def dashboard(
        flags: FeatureFlags = Depends(get_user_feature_flags),
        current_user: Tuple[str, str] = Depends(get_current_user)
    ):
        return {
            "sync_available": flags.sync_enabled,
            "ai_available": flags.ai_enabled,
            "is_supporter": flags.supporter
        }
    ```

    Returns:
        FeatureFlags object
    """
    user_id, _ = current_user
    flags_response = add_ons_service.get_feature_flags(user_id)
    return flags_response.flags
