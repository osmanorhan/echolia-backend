"""
Authentication API routes for OAuth-based authentication.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Tuple
import structlog

from app.auth.models import (
    OAuthSignInRequest,
    OAuthSignInResponse,
    RefreshTokenRequest,
    RefreshTokenResponse,
    DevicesResponse,
    DeviceInfo,
    DeleteDeviceResponse,
    UserInfoResponse
)
from app.auth.service import AuthService
from app.auth.dependencies import get_current_user
from app.database import get_db_manager, TursoDatabaseManager
from app.master_db import get_master_db_manager, MasterDatabaseManager


logger = structlog.get_logger()
router = APIRouter(prefix="/auth", tags=["authentication"])


def get_auth_service(
    master_db: MasterDatabaseManager = Depends(get_master_db_manager),
    user_db_manager: TursoDatabaseManager = Depends(get_db_manager)
) -> AuthService:
    """Dependency to get auth service with both databases."""
    return AuthService(master_db, user_db_manager)


# ========== OAuth Sign-In ==========

@router.post("/oauth/signin", response_model=OAuthSignInResponse)
async def oauth_signin(
    request: OAuthSignInRequest,
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Sign in with OAuth (Google or Apple).

    Flow:
    1. Client performs OAuth with provider (Google/Apple)
    2. Client receives id_token (JWT) from provider
    3. Client sends id_token + device info to this endpoint
    4. Server verifies id_token with provider
    5. Server creates/updates user and device
    6. Server returns access_token + refresh_token + add-ons

    This is the primary entry point for authentication.
    """
    try:
        response = await auth_service.sign_in_with_oauth(request)
        return response

    except ValueError as e:
        logger.error("oauth_signin_value_error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )
    except Exception as e:
        logger.error("oauth_signin_error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OAuth sign-in failed"
        )


# ========== Token Management ==========

@router.post("/refresh", response_model=RefreshTokenResponse)
async def refresh_token(
    request: RefreshTokenRequest,
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Refresh access token using refresh token.

    Access tokens expire in 1 hour. Use this endpoint to get a new access token
    without requiring the user to sign in again.

    Both access_token and refresh_token are rotated for security.
    """
    result = auth_service.refresh_access_token(request.refresh_token)

    if not result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token"
        )

    return result


# ========== Device Management ==========

@router.get("/devices", response_model=DevicesResponse)
async def list_devices(
    current_user: Tuple[str, str] = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    List all devices registered to the current user's account.

    Shows device name, platform, last seen timestamp, etc.
    """
    user_id, _ = current_user

    try:
        devices = auth_service.get_user_devices(user_id)
        return DevicesResponse(devices=devices)

    except Exception as e:
        logger.error("list_devices_error", user_id=user_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve devices"
        )


@router.delete("/device/{device_id}", response_model=DeleteDeviceResponse)
async def delete_device(
    device_id: str,
    current_user: Tuple[str, str] = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Delete a device from the user's account.

    The device will no longer be able to access the account.
    Tokens issued for that device will become invalid.

    Note: You cannot delete the device you're currently using.
    """
    user_id, current_device_id = current_user

    # Prevent user from deleting their current device
    if device_id == current_device_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete current device"
        )

    try:
        success = await auth_service.delete_device(user_id, device_id)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Device not found"
            )

        return DeleteDeviceResponse(
            success=True,
            message="Device deleted successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("delete_device_error", user_id=user_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete device"
        )


# ========== User Info ==========

@router.get("/me", response_model=UserInfoResponse)
async def get_current_user_info(
    current_user: Tuple[str, str] = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Get current user's information.

    Returns:
    - User ID
    - OAuth provider (google/apple)
    - Email (may be null if user chose to hide it)
    - Name (may be null)
    - Account creation date
    - Active add-ons (sync, AI, supporter)
    """
    user_id, _ = current_user

    try:
        user_info = auth_service.get_user_info(user_id)

        if not user_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        return user_info

    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_user_info_error", user_id=user_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve user info"
        )
