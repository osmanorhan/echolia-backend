"""
E2EE inference API routes.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Tuple
import structlog

from app.inference.models import (
    PublicKeyResponse,
    E2EEInferenceRequest,
    E2EEInferenceResponse,
    ProviderInfo
)
from app.inference.service import get_inference_service
from app.auth.dependencies import get_current_user


logger = structlog.get_logger()

router = APIRouter(prefix="/inference", tags=["inference"])


@router.get("/public-key", response_model=PublicKeyResponse)
async def get_public_key():
    """
    Get server's X25519 public key for E2EE.

    Returns the server's public key that clients use to establish
    a shared secret for encrypting inference requests.
    """
    try:
        service = get_inference_service()
        return service.get_public_key()

    except Exception as e:
        logger.error("get_public_key_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve public key"
        )


@router.get("/provider", response_model=ProviderInfo)
async def get_provider_info():
    """
    Get the currently configured inference provider and model.
    """
    try:
        service = get_inference_service()
        return service.get_provider_info()

    except Exception as e:
        logger.error("get_provider_info_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve provider information"
        )


@router.post("/execute", response_model=E2EEInferenceResponse)
async def execute_inference(
    request: E2EEInferenceRequest,
    current_user: Tuple[str, str] = Depends(get_current_user)
):
    """
    Execute an AI inference task with E2EE.

    Flow:
    1. Client encrypts content with server's public key
    2. Server decrypts, processes, and re-encrypts response
    3. Only client can decrypt the result

    Rate Limits:
    - Free tier: 10 requests/day
    - AI add-on: 5000 requests/day (anti-abuse)

    Tasks:
    - memory_distillation: Extract commitments, facts, insights
    - tagging: Extract relevant tags
    - insight_extraction: Extract deeper insights and patterns
    """
    user_id, device_id = current_user

    logger.info(
        "e2ee_inference_request",
        user_id=user_id,
        device_id=device_id,
        task=request.task,
        client_version=request.client_version
    )

    service = get_inference_service()

    try:
        response = await service.execute_inference(user_id, request)
        return response

    except ValueError as e:
        error_message = str(e)
        logger.warning(
            "e2ee_inference_value_error_response",
            user_id=user_id,
            device_id=device_id,
            task=request.task,
            error=error_message,
        )

        if "Rate limit exceeded" in error_message:
            # Return rate limit error with usage info
            usage = service.get_usage_info(user_id)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "Daily request limit reached",
                    "usage": {
                        "requests_remaining": usage.requests_remaining,
                        "reset_at": usage.reset_at,
                        "tier": usage.tier
                    }
                }
            )

        elif "Decryption failed" in error_message or "Failed to derive" in error_message:
            # Encryption/decryption error
            logger.warning(
                "e2ee_inference_decryption_failed_response",
                user_id=user_id,
                device_id=device_id,
                task=request.task,
                encrypted_len=len(request.encrypted_content or ""),
                nonce_len=len(request.nonce or ""),
                mac_len=len(request.mac or ""),
                client_pub_len=len(request.ephemeral_public_key or ""),
                detail=error_message,
                status_code=422,
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Decryption failed - invalid encryption"
            )

        else:
            # Other ValueError
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_message
            )

    except Exception as e:
        logger.error(
            "e2ee_inference_error",
            user_id=user_id,
            task=request.task,
            error=str(e)
        )

        # Check for LLM service availability
        if "No LLM provider" in str(e):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="LLM backend unavailable"
            )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal processing error"
        )


@router.get("/usage")
async def get_usage(
    current_user: Tuple[str, str] = Depends(get_current_user)
):
    """
    Get current user's inference usage quota.

    Returns remaining requests and reset time.
    """
    user_id, device_id = current_user

    try:
        service = get_inference_service()
        usage = service.get_usage_info(user_id)

        return {
            "requests_remaining": usage.requests_remaining,
            "reset_at": usage.reset_at,
            "tier": usage.tier
        }

    except Exception as e:
        logger.error("get_usage_failed", user_id=user_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve usage information"
        )
