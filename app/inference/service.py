"""
E2EE inference service with privacy-first processing.
"""
import time
import structlog
from datetime import datetime, timedelta

from app.inference.models import (
    E2EEInferenceRequest,
    E2EEInferenceResponse,
    UsageInfo,
    PublicKeyResponse
)
from app.inference.crypto import e2ee_crypto
from app.inference.tasks import task_processor
from app.master_db import MasterDatabaseManager
from app.config import settings


logger = structlog.get_logger()


class E2EEInferenceService:
    """
    E2EE inference service with:
    - X25519 key exchange + ChaCha20-Poly1305 encryption
    - Rate limiting (free: 10/day, paid: unlimited)
    - Zero-knowledge processing (no plaintext logging)
    """

    def __init__(self, master_db: MasterDatabaseManager):
        self.master_db = master_db
        self.free_tier_limit = settings.inference_free_tier_daily_limit
        self.paid_tier_limit = settings.inference_paid_tier_daily_limit

    def get_public_key(self) -> PublicKeyResponse:
        """
        Get server's X25519 public key for client encryption.

        Returns:
            PublicKeyResponse with key info
        """
        key_info = e2ee_crypto.get_public_key_info()
        return PublicKeyResponse(**key_info)

    def get_user_tier(self, user_id: str) -> str:
        """
        Determine user's tier based on add-ons.

        Args:
            user_id: User UUID

        Returns:
            'free' or 'paid'
        """
        has_ai_addon = self.master_db.is_add_on_active(user_id, "ai")
        return "paid" if has_ai_addon else "free"

    def get_usage_info(self, user_id: str) -> UsageInfo:
        """
        Get user's current usage quota information.

        Args:
            user_id: User UUID

        Returns:
            UsageInfo with remaining requests and reset time
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

        # Calculate limits based on tier
        if tier == "paid":
            daily_limit = self.paid_tier_limit
        else:
            daily_limit = self.free_tier_limit

        requests_remaining = max(0, daily_limit - requests_today)

        # Calculate reset time (next midnight UTC)
        tomorrow = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        reset_at = tomorrow.isoformat() + "Z"

        return UsageInfo(
            requests_remaining=requests_remaining,
            reset_at=reset_at,
            tier=tier
        )

    def check_and_update_quota(self, user_id: str) -> bool:
        """
        Check if user can make a request and update quota.

        Args:
            user_id: User UUID

        Returns:
            True if user can make request, False if quota exceeded
        """
        usage = self.get_usage_info(user_id)

        if usage.requests_remaining <= 0:
            logger.warning(
                "e2ee_inference_quota_exceeded",
                user_id=user_id,
                tier=usage.tier
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
            "e2ee_inference_quota_updated",
            user_id=user_id,
            tier=usage.tier,
            remaining=usage.requests_remaining - 1
        )

        return True

    async def execute_inference(
        self,
        user_id: str,
        request: E2EEInferenceRequest
    ) -> E2EEInferenceResponse:
        """
        Execute E2EE inference task.

        Flow:
        1. Check rate limits
        2. Derive shared secret
        3. Decrypt content
        4. Execute task
        5. Encrypt response
        6. Return encrypted result

        Args:
            user_id: User UUID
            request: E2EE inference request

        Returns:
            E2EEInferenceResponse with encrypted result

        Raises:
            ValueError: If quota exceeded or decryption fails
        """
        # 1. Check rate limits (before any processing)
        if not self.check_and_update_quota(user_id):
            raise ValueError("Rate limit exceeded")

        plaintext_content = None
        result_json = None
        encryption_key = None

        try:
            logger.info(
                "e2ee_inference_start",
                user_id=user_id,
                task=request.task,
                client_version=request.client_version
            )

            # 2. Derive shared secret using X25519
            encryption_key = e2ee_crypto.derive_shared_secret(request.ephemeral_public_key)

            # 3. Decrypt content
            plaintext_content = e2ee_crypto.decrypt_content(
                request.encrypted_content,
                request.nonce,
                request.mac,
                encryption_key
            )

            # CRITICAL: Do NOT log plaintext_content
            # logger.debug("Content length", length=len(plaintext_content))

            # 4. Execute task (in ephemeral memory)
            result_json = await task_processor.process_task(request.task, plaintext_content)

            # 5. Encrypt response with SAME shared secret
            encrypted_result, response_nonce, response_mac = e2ee_crypto.encrypt_response(
                result_json,
                encryption_key
            )

            # 6. Get updated usage info
            usage = self.get_usage_info(user_id)

            logger.info(
                "e2ee_inference_complete",
                user_id=user_id,
                task=request.task,
                remaining=usage.requests_remaining
            )

            return E2EEInferenceResponse(
                encrypted_result=encrypted_result,
                nonce=response_nonce,
                mac=response_mac,
                usage=usage
            )

        except ValueError as e:
            # Re-raise ValueError (quota, decryption issues)
            raise

        except Exception as e:
            logger.error(
                "e2ee_inference_failed",
                user_id=user_id,
                task=request.task,
                error=str(e)
            )
            raise

        finally:
            # Clear sensitive data from memory
            if plaintext_content is not None:
                plaintext_content = None
            if result_json is not None:
                result_json = None
            if encryption_key is not None:
                encryption_key = None


# Global service instance (will be initialized with master_db)
_inference_service = None


def get_inference_service() -> E2EEInferenceService:
    """Get or create the E2EE inference service instance."""
    global _inference_service

    if _inference_service is None:
        from app.master_db import master_db_manager
        _inference_service = E2EEInferenceService(master_db_manager)

    return _inference_service
