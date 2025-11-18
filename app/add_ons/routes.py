"""
Add-ons API routes.

Provides endpoints for querying add-on status and feature flags.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Tuple
import structlog

from app.add_ons.models import AddOnsStatusResponse, FeatureFlagsResponse
from app.add_ons.service import AddOnsService
from app.auth.dependencies import get_current_user
from app.master_db import get_master_db_manager, MasterDatabaseManager


logger = structlog.get_logger()
router = APIRouter(prefix="/add-ons", tags=["add-ons"])


def get_add_ons_service(
    master_db: MasterDatabaseManager = Depends(get_master_db_manager)
) -> AddOnsService:
    """Dependency to get add-ons service."""
    return AddOnsService(master_db)


# ========== Add-Ons Status Endpoints ==========

@router.get("/status", response_model=AddOnsStatusResponse)
async def get_add_ons_status(
    current_user: Tuple[str, str] = Depends(get_current_user),
    add_ons_service: AddOnsService = Depends(get_add_ons_service)
):
    """
    Get user's add-ons status.

    Returns detailed information about all add-ons:
    - Sync Add-on ($2/month) - Cross-device synchronization
    - AI Add-on ($3/month) - Server-side AI inference
    - Support Echolia ($5-$50 one-time) - Thank you badge

    Each add-on includes:
    - Status (active, expired, cancelled)
    - Platform (ios, android)
    - Purchase and expiration dates
    - Auto-renewal status

    This endpoint requires authentication but no specific add-on.
    """
    user_id, _ = current_user

    try:
        status = add_ons_service.get_add_ons_status(user_id)
        return status

    except Exception as e:
        logger.error("get_add_ons_status_error", user_id=user_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve add-ons status"
        )


@router.get("/features", response_model=FeatureFlagsResponse)
async def get_feature_flags(
    current_user: Tuple[str, str] = Depends(get_current_user),
    add_ons_service: AddOnsService = Depends(get_add_ons_service)
):
    """
    Get feature flags based on active add-ons.

    Returns a simplified boolean flags object:
    - sync_enabled: User can use sync features
    - ai_enabled: User has AI Add-on (note: free tier still gets 10 requests/day)
    - supporter: User has purchased Support Echolia

    Useful for conditional UI rendering in client apps.
    This endpoint requires authentication but no specific add-on.
    """
    user_id, _ = current_user

    try:
        flags = add_ons_service.get_feature_flags(user_id)
        return flags

    except Exception as e:
        logger.error("get_feature_flags_error", user_id=user_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve feature flags"
        )
