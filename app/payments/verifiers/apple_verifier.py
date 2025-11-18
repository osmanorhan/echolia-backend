"""
Apple App Store receipt verification.

Uses Apple's App Store Server API to verify purchase receipts.
"""
import httpx
import structlog
from typing import Optional
from datetime import datetime

from app.payments.models import (
    AppleReceiptInfo,
    AppleVerificationResponse,
    VerifiedReceipt,
    ReceiptPlatform
)
from app.config import settings


logger = structlog.get_logger()


# Apple App Store Server URLs
APPLE_PRODUCTION_URL = "https://buy.itunes.apple.com/verifyReceipt"
APPLE_SANDBOX_URL = "https://sandbox.itunes.apple.com/verifyReceipt"


class AppleReceiptVerifier:
    """
    Verifies Apple App Store receipts.

    Uses Apple's App Store Server API with automatic sandbox fallback.
    """

    def __init__(self, shared_secret: Optional[str] = None):
        """
        Initialize Apple receipt verifier.

        Args:
            shared_secret: Apple shared secret for subscription verification
        """
        self.shared_secret = shared_secret or settings.apple_shared_secret

    async def verify_receipt(self, receipt_data: str) -> Optional[VerifiedReceipt]:
        """
        Verify an Apple App Store receipt.

        Args:
            receipt_data: Base64-encoded receipt data

        Returns:
            VerifiedReceipt if valid, None if invalid

        Raises:
            Exception: If verification fails
        """
        try:
            # Try production first
            response = await self._verify_with_apple(receipt_data, APPLE_PRODUCTION_URL)

            # If status is 21007, receipt is for sandbox, retry with sandbox URL
            if response.status == 21007:
                logger.info("apple_receipt_is_sandbox_retrying")
                response = await self._verify_with_apple(receipt_data, APPLE_SANDBOX_URL)

            # Check verification status
            if response.status != 0:
                logger.warning(
                    "apple_receipt_verification_failed",
                    status=response.status,
                    retryable=response.is_retryable
                )
                return None

            # Extract receipt information
            receipt_info = self._extract_receipt_info(response)

            if not receipt_info:
                logger.error("apple_receipt_info_extraction_failed")
                return None

            # Convert to VerifiedReceipt
            verified = self._convert_to_verified_receipt(receipt_info, response)

            logger.info(
                "apple_receipt_verified",
                product_id=verified.product_id,
                transaction_id=verified.transaction_id,
                is_subscription=verified.is_subscription
            )

            return verified

        except Exception as e:
            logger.error("apple_receipt_verification_error", error=str(e))
            raise

    async def _verify_with_apple(
        self,
        receipt_data: str,
        verify_url: str
    ) -> AppleVerificationResponse:
        """
        Call Apple's verification API.

        Args:
            receipt_data: Base64-encoded receipt
            verify_url: Apple verification URL (production or sandbox)

        Returns:
            AppleVerificationResponse
        """
        payload = {
            "receipt-data": receipt_data,
            "exclude-old-transactions": True
        }

        # Add shared secret for subscription verification
        if self.shared_secret:
            payload["password"] = self.shared_secret

        async with httpx.AsyncClient() as client:
            response = await client.post(
                verify_url,
                json=payload,
                timeout=30.0
            )

            response.raise_for_status()
            data = response.json()

            return AppleVerificationResponse(
                status=data.get("status", -1),
                environment=data.get("environment", "unknown"),
                receipt=data.get("receipt"),
                latest_receipt_info=data.get("latest_receipt_info"),
                pending_renewal_info=data.get("pending_renewal_info"),
                is_retryable=data.get("is-retryable", False)
            )

    def _extract_receipt_info(
        self,
        response: AppleVerificationResponse
    ) -> Optional[AppleReceiptInfo]:
        """
        Extract receipt information from Apple's response.

        For subscriptions, uses latest_receipt_info.
        For one-time purchases, uses receipt.in_app.

        Args:
            response: Apple verification response

        Returns:
            AppleReceiptInfo or None
        """
        # For subscriptions, use latest_receipt_info
        if response.latest_receipt_info:
            latest = response.latest_receipt_info[-1]  # Most recent
            return AppleReceiptInfo(
                product_id=latest.get("product_id"),
                transaction_id=latest.get("transaction_id"),
                original_transaction_id=latest.get("original_transaction_id"),
                purchase_date_ms=int(latest.get("purchase_date_ms", 0)),
                expires_date_ms=int(latest.get("expires_date_ms", 0)) if latest.get("expires_date_ms") else None,
                is_trial_period=latest.get("is_trial_period") == "true",
                is_in_intro_offer_period=latest.get("is_in_intro_offer_period") == "true",
                cancellation_date_ms=int(latest.get("cancellation_date_ms", 0)) if latest.get("cancellation_date_ms") else None,
                auto_renew_status=response.pending_renewal_info[0].get("auto_renew_status") == "1" if response.pending_renewal_info else None
            )

        # For one-time purchases, use receipt.in_app
        if response.receipt and "in_app" in response.receipt and response.receipt["in_app"]:
            purchase = response.receipt["in_app"][-1]  # Most recent
            return AppleReceiptInfo(
                product_id=purchase.get("product_id"),
                transaction_id=purchase.get("transaction_id"),
                original_transaction_id=purchase.get("original_transaction_id"),
                purchase_date_ms=int(purchase.get("purchase_date_ms", 0)),
                expires_date_ms=None,  # One-time purchases don't expire
                is_trial_period=False,
                is_in_intro_offer_period=False,
                cancellation_date_ms=None,
                auto_renew_status=None
            )

        return None

    def _convert_to_verified_receipt(
        self,
        receipt_info: AppleReceiptInfo,
        response: AppleVerificationResponse
    ) -> VerifiedReceipt:
        """
        Convert Apple receipt info to VerifiedReceipt.

        Args:
            receipt_info: Apple receipt information
            response: Apple verification response

        Returns:
            VerifiedReceipt
        """
        # Convert milliseconds to seconds
        purchase_date = receipt_info.purchase_date_ms // 1000
        expires_at = receipt_info.expires_date_ms // 1000 if receipt_info.expires_date_ms else None

        # Determine if subscription
        is_subscription = receipt_info.expires_date_ms is not None

        return VerifiedReceipt(
            platform=ReceiptPlatform.IOS,
            product_id=receipt_info.product_id,
            transaction_id=receipt_info.transaction_id,
            original_transaction_id=receipt_info.original_transaction_id,
            purchase_date=purchase_date,
            expires_at=expires_at,
            auto_renew=receipt_info.auto_renew_status or False,
            is_subscription=is_subscription,
            environment=response.environment
        )
