"""
LLM inference service with tier-based access control.
"""
import time
import structlog
from typing import Optional, List
from datetime import datetime

from app.llm.models import (
    InferenceRequest,
    InferenceResponse,
    UsageTier,
    UsageQuota,
    ModelInfo,
    ModelsResponse,
    UsageResponse,
    ModelType
)
from app.master_db import MasterDatabaseManager
from app.config import settings


logger = structlog.get_logger()


class LLMService:
    """
    LLM inference service with two-tier access:

    1. Free Tier: 10 requests/day (no add-on needed)
    2. AI Add-on: Fair usage with higher limits (500/hour, 5000/day)
    """

    def __init__(self, master_db: MasterDatabaseManager):
        self.master_db = master_db

    def get_user_tier(self, user_id: str) -> UsageTier:
        """
        Determine user's usage tier.

        Args:
            user_id: User UUID

        Returns:
            UsageTier (FREE or AI_ADD_ON)
        """
        has_ai_addon = self.master_db.is_add_on_active(user_id, "ai")

        if has_ai_addon:
            return UsageTier.AI_ADD_ON
        else:
            return UsageTier.FREE

    def get_usage_quota(self, user_id: str) -> UsageQuota:
        """
        Get user's current usage quota.

        Args:
            user_id: User UUID

        Returns:
            UsageQuota with limits and remaining requests
        """
        tier = self.get_user_tier(user_id)
        today = datetime.utcnow().strftime("%Y-%m-%d")

        # Get today's usage from master database
        conn = self.master_db.get_connection()
        result = conn.execute(
            "SELECT request_count FROM ai_usage_quota WHERE user_id = ? AND date = ?",
            [user_id, today]
        )

        requests_today = 0
        if result.rows:
            requests_today = result.rows[0][0]

        if tier == UsageTier.AI_ADD_ON:
            # AI Add-on: Fair usage limits (anti-abuse, not paywall)
            daily_limit = settings.ai_rate_limit_daily
            hourly_limit = settings.ai_rate_limit_hourly
        else:
            # Free tier: 10 requests/day
            daily_limit = 10
            hourly_limit = None

        requests_remaining = max(0, daily_limit - requests_today)
        can_make_request = requests_remaining > 0

        return UsageQuota(
            tier=tier,
            requests_today=requests_today,
            daily_limit=daily_limit,
            requests_remaining=requests_remaining,
            hourly_limit=hourly_limit,
            can_make_request=can_make_request
        )

    def check_and_update_quota(self, user_id: str) -> bool:
        """
        Check if user can make a request and update quota.

        Args:
            user_id: User UUID

        Returns:
            True if user can make request, False if quota exceeded
        """
        quota = self.get_usage_quota(user_id)

        if not quota.can_make_request:
            logger.warning(
                "quota_exceeded",
                user_id=user_id,
                tier=quota.tier,
                requests_today=quota.requests_today,
                daily_limit=quota.daily_limit
            )
            return False

        # Update quota in database
        today = datetime.utcnow().strftime("%Y-%m-%d")
        current_time = int(time.time())

        conn = self.master_db.get_connection()

        # Upsert request count
        conn.execute(
            """
            INSERT INTO ai_usage_quota (user_id, date, request_count, last_reset_at)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(user_id, date) DO UPDATE SET
                request_count = request_count + 1,
                last_reset_at = excluded.last_reset_at
            """,
            [user_id, today, current_time]
        )
        conn.commit()

        logger.info(
            "quota_updated",
            user_id=user_id,
            tier=quota.tier,
            requests_today=quota.requests_today + 1,
            daily_limit=quota.daily_limit
        )

        return True

    async def generate(
        self,
        user_id: str,
        request: InferenceRequest
    ) -> InferenceResponse:
        """
        Generate LLM response.

        Args:
            user_id: User UUID
            request: Inference request

        Returns:
            InferenceResponse

        Raises:
            ValueError: If quota exceeded or model unavailable
        """
        # Check quota
        if not self.check_and_update_quota(user_id):
            tier = self.get_user_tier(user_id)
            if tier == UsageTier.FREE:
                raise ValueError(
                    "Free tier limit reached (10 requests/day). "
                    "Upgrade to AI Add-on for unlimited access with fair usage."
                )
            else:
                raise ValueError(
                    "Daily usage limit reached (5000 requests/day). "
                    "This is an anti-abuse limit. Please try again tomorrow."
                )

        # Get provider for model
        from app.llm.providers.anthropic import AnthropicProvider
        from app.llm.providers.openai import OpenAIProvider
        from app.llm.providers.google import GoogleProvider

        provider = None

        if request.model in [ModelType.CLAUDE_HAIKU, ModelType.CLAUDE_SONNET]:
            provider = AnthropicProvider()
        elif request.model in [ModelType.GPT_4O_MINI, ModelType.GPT_4O]:
            provider = OpenAIProvider()
        elif request.model in [ModelType.GEMINI_FLASH, ModelType.GEMINI_PRO]:
            provider = GoogleProvider()
        else:
            raise ValueError(f"Unsupported model: {request.model}")

        # Generate response
        logger.info(
            "llm_inference_start",
            user_id=user_id,
            model=request.model,
            message_count=len(request.messages)
        )

        response = await provider.generate(request)

        logger.info(
            "llm_inference_complete",
            user_id=user_id,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens
        )

        # Track usage in per-user database (for transparency)
        await self._track_usage(user_id, response)

        return response

    async def _track_usage(self, user_id: str, response: InferenceResponse) -> None:
        """Track LLM usage in per-user database for transparency."""
        try:
            from app.database import db_manager
            import uuid

            db = db_manager.get_user_db(user_id)

            current_time = int(time.time())
            usage_id = str(uuid.uuid4())

            db.execute(
                """
                INSERT INTO llm_usage (id, model, input_tokens, output_tokens, cost_usd, created_at)
                VALUES (?, ?, ?, ?, NULL, ?)
                """,
                [
                    usage_id,
                    response.model,
                    response.usage.input_tokens,
                    response.usage.output_tokens,
                    current_time
                ]
            )
            db_manager.commit_and_sync(db, user_id)

        except Exception as e:
            # Don't fail the request if usage tracking fails
            logger.error("usage_tracking_failed", user_id=user_id, error=str(e))

    def get_available_models(self, user_id: str) -> ModelsResponse:
        """
        Get list of available models for user.

        Args:
            user_id: User UUID

        Returns:
            ModelsResponse with available models and user tier
        """
        tier = self.get_user_tier(user_id)

        models = [
            ModelInfo(
                id=ModelType.CLAUDE_HAIKU,
                name="Claude 3 Haiku",
                provider="anthropic",
                context_window=200000,
                requires_add_on=False
            ),
            ModelInfo(
                id=ModelType.CLAUDE_SONNET,
                name="Claude 3.5 Sonnet",
                provider="anthropic",
                context_window=200000,
                requires_add_on=False
            ),
            ModelInfo(
                id=ModelType.GPT_4O_MINI,
                name="GPT-4o Mini",
                provider="openai",
                context_window=128000,
                requires_add_on=False
            ),
            ModelInfo(
                id=ModelType.GPT_4O,
                name="GPT-4o",
                provider="openai",
                context_window=128000,
                requires_add_on=False
            ),
            ModelInfo(
                id=ModelType.GEMINI_FLASH,
                name="Gemini 1.5 Flash",
                provider="google",
                context_window=1000000,
                requires_add_on=False
            ),
            ModelInfo(
                id=ModelType.GEMINI_PRO,
                name="Gemini 1.5 Pro",
                provider="google",
                context_window=2000000,
                requires_add_on=False
            ),
        ]

        return ModelsResponse(models=models, user_tier=tier)

    def get_usage_stats(self, user_id: str) -> UsageResponse:
        """
        Get user's usage statistics.

        Args:
            user_id: User UUID

        Returns:
            UsageResponse with quota and all-time stats
        """
        tier = self.get_user_tier(user_id)
        quota = self.get_usage_quota(user_id)

        # Get all-time stats from per-user database
        total_requests = 0
        total_tokens = 0

        try:
            from app.database import db_manager

            db = db_manager.get_user_db(user_id)

            # Count total requests
            result = db.execute("SELECT COUNT(*) FROM llm_usage")
            if result.rows:
                total_requests = result.rows[0][0]

            # Sum total tokens
            result = db.execute(
                "SELECT SUM(input_tokens + output_tokens) FROM llm_usage"
            )
            if result.rows and result.rows[0][0] is not None:
                total_tokens = result.rows[0][0]

        except Exception as e:
            logger.error("get_usage_stats_failed", user_id=user_id, error=str(e))

        return UsageResponse(
            tier=tier,
            quota=quota,
            total_requests_all_time=total_requests,
            total_tokens_all_time=total_tokens
        )
