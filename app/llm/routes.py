"""
LLM inference API routes.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Tuple
import structlog

from app.llm.models import (
    InferenceRequest,
    InferenceResponse,
    ModelsResponse,
    UsageResponse
)
from app.llm.service import LLMService
from app.auth.dependencies import get_current_user
from app.master_db import get_master_db_manager, MasterDatabaseManager


logger = structlog.get_logger()
router = APIRouter(prefix="/llm", tags=["llm"])


def get_llm_service(
    master_db: MasterDatabaseManager = Depends(get_master_db_manager)
) -> LLMService:
    """Dependency to get LLM service."""
    return LLMService(master_db)


# ========== LLM Inference ==========

@router.post("/generate", response_model=InferenceResponse)
async def generate(
    request: InferenceRequest,
    current_user: Tuple[str, str] = Depends(get_current_user),
    llm_service: LLMService = Depends(get_llm_service)
):
    """
    Generate LLM response with tier-based access:

    - **Free Tier**: 10 requests/day (no add-on needed)
    - **AI Add-on**: Fair usage with higher limits (500/hour, 5000/day)

    This endpoint is available to all authenticated users. Users without
    capable devices get 10 free requests per day to try the AI feature.
    Users with the AI Add-on get unlimited access with fair usage limits.

    The request will fail if:
    - Free tier user exceeds 10 requests/day
    - AI Add-on user exceeds fair usage limits (5000/day)
    - Invalid model specified
    - API key not configured for the selected model
    """
    user_id, _ = current_user

    try:
        response = await llm_service.generate(user_id, request)
        return response

    except ValueError as e:
        error_msg = str(e)

        # Determine appropriate status code
        if "limit reached" in error_msg.lower():
            status_code = status.HTTP_429_TOO_MANY_REQUESTS
        elif "not configured" in error_msg.lower():
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        else:
            status_code = status.HTTP_400_BAD_REQUEST

        raise HTTPException(
            status_code=status_code,
            detail=error_msg
        )

    except Exception as e:
        logger.error("llm_generation_error", user_id=user_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="LLM generation failed"
        )


# ========== Available Models ==========

@router.get("/models", response_model=ModelsResponse)
async def list_models(
    current_user: Tuple[str, str] = Depends(get_current_user),
    llm_service: LLMService = Depends(get_llm_service)
):
    """
    Get list of available LLM models.

    Returns all models available to the user, along with their tier status.
    All models are available to both free and AI Add-on users - the only
    difference is the daily request limit.

    Free tier users can use any model, but are limited to 10 requests/day.
    AI Add-on users can use any model with fair usage limits.
    """
    user_id, _ = current_user

    try:
        return llm_service.get_available_models(user_id)

    except Exception as e:
        logger.error("list_models_error", user_id=user_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve models"
        )


# ========== Usage Statistics ==========

@router.get("/usage", response_model=UsageResponse)
async def get_usage(
    current_user: Tuple[str, str] = Depends(get_current_user),
    llm_service: LLMService = Depends(get_llm_service)
):
    """
    Get user's LLM usage statistics.

    Returns:
    - Current tier (free or AI Add-on)
    - Today's quota (requests used, remaining, limits)
    - All-time statistics (total requests, total tokens)

    This endpoint provides full transparency into LLM usage, allowing users
    to understand their consumption and make informed decisions about
    upgrading to the AI Add-on.
    """
    user_id, _ = current_user

    try:
        return llm_service.get_usage_stats(user_id)

    except Exception as e:
        logger.error("get_usage_error", user_id=user_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve usage statistics"
        )
