"""
Authentication API routes.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Tuple
import structlog

from app.auth.models import (
    RegisterRequest, RegisterResponse, PairDeviceRequest,
    TokenResponse, DeviceInfo
)
from app.auth.service import AuthService
from app.auth.dependencies import get_current_user
from app.database import get_db_manager, TursoDatabaseManager


logger = structlog.get_logger()
router = APIRouter(prefix="/auth", tags=["authentication"])


def get_auth_service(
    db_manager: TursoDatabaseManager = Depends(get_db_manager)
) -> AuthService:
    """Dependency to get auth service."""
    return AuthService(db_manager)


@router.post("/register", response_model=RegisterResponse)
async def register(
    request: RegisterRequest,
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Register a new anonymous user with their first device.

    No email or password required. User gets a unique ID and token.
    """
    try:
        user_id, device_id, access_token, refresh_token = await auth_service.register_user(request)

        return RegisterResponse(
            user_id=user_id,
            device_id=device_id,
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer"
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error("register_endpoint_error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration failed"
        )


@router.post("/pair-device", response_model=TokenResponse)
async def pair_device(
    request: PairDeviceRequest,
    current_user: Tuple[str, str] = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Pair a new device to the current user's account.

    Requires authentication from an existing device.
    """
    user_id, _ = current_user

    try:
        device_id, access_token, refresh_token = await auth_service.pair_device(
            user_id, request
        )

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=3600  # 1 hour
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error("pair_device_endpoint_error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Device pairing failed"
        )


@router.get("/devices", response_model=list[DeviceInfo])
async def list_devices(
    current_user: Tuple[str, str] = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    List all devices paired to the current user's account.
    """
    user_id, _ = current_user

    try:
        devices = auth_service.get_devices(user_id)
        return devices

    except Exception as e:
        logger.error("list_devices_endpoint_error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve devices"
        )


@router.delete("/device/{device_id}")
async def revoke_device(
    device_id: str,
    current_user: Tuple[str, str] = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Revoke access for a specific device.

    Device will no longer be able to sync or access the account.
    """
    user_id, current_device_id = current_user

    # Prevent user from revoking their current device
    if device_id == current_device_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot revoke current device"
        )

    try:
        success = await auth_service.revoke_device(user_id, device_id)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Device not found"
            )

        return {"message": "Device revoked successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("revoke_device_endpoint_error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to revoke device"
        )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    refresh_token: str,
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Refresh access token using refresh token.
    """
    result = auth_service.refresh_access_token(refresh_token)

    if not result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token"
        )

    access_token, new_refresh_token = result

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=3600
    )
