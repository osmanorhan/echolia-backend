"""
Google Play Store receipt verification.

Uses Google Play Developer API to verify purchase receipts.
"""
import httpx
import structlog
import json
from typing import Optional
from google.oauth2 import service_account
from google.auth.transport.requests import Request

from app.payments.models import (
    GoogleReceiptInfo,
    GoogleVerificationResponse,
    VerifiedReceipt,
    ReceiptPlatform
)
from app.config import settings


logger = structlog.get_logger()


# Google Play Developer API
GOOGLE_PLAY_API_BASE = "https://androidpublisher.googleapis.com/androidpublisher/v3"
GOOGLE_PLAY_SCOPES = ["https://www.googleapis.com/auth/androidpublisher"]


class GoogleReceiptVerifier:
    """
    Verifies Google Play Store receipts.

    Uses Google Play Developer API with service account authentication.
    """

    def __init__(self, service_account_json: Optional[str] = None):
        """
        Initialize Google receipt verifier.

        Args:
            service_account_json: JSON string or path to service account credentials
        """
        self.service_account_json = service_account_json or settings.google_service_account_json
        self._credentials = None

    def _get_credentials(self):
        """
        Get or create Google service account credentials.

        Returns:
            Google service account credentials
        """
        if self._credentials:
            return self._credentials

        if not self.service_account_json:
            raise ValueError("Google service account JSON not configured")

        try:
            # Try to parse as JSON first (inline credentials)
            creds_data = json.loads(self.service_account_json)
            self._credentials = service_account.Credentials.from_service_account_info(
                creds_data,
                scopes=GOOGLE_PLAY_SCOPES
            )
        except json.JSONDecodeError:
            # If not JSON, treat as file path
            self._credentials = service_account.Credentials.from_service_account_file(
                self.service_account_json,
                scopes=GOOGLE_PLAY_SCOPES
            )

        return self._credentials

    async def verify_subscription(
        self,
        package_name: str,
        subscription_id: str,
        purchase_token: str
    ) -> Optional[VerifiedReceipt]:
        """
        Verify a Google Play subscription purchase.

        Args:
            package_name: Android app package name
            subscription_id: Subscription product ID
            purchase_token: Purchase token from Google Play

        Returns:
            VerifiedReceipt if valid, None if invalid
        """
        try:
            # Get access token
            credentials = self._get_credentials()
            credentials.refresh(Request())
            access_token = credentials.token

            # Call Google Play API
            url = (
                f"{GOOGLE_PLAY_API_BASE}/applications/{package_name}/"
                f"purchases/subscriptions/{subscription_id}/tokens/{purchase_token}"
            )

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=30.0
                )

                response.raise_for_status()
                data = response.json()

            # Parse response
            verification = GoogleVerificationResponse(
                kind=data.get("kind", ""),
                purchase_token=purchase_token,
                product_id=subscription_id,
                purchase_time_millis=int(data.get("startTimeMillis", 0)),
                purchase_state=data.get("paymentState"),
                acknowledgement_state=data.get("acknowledgementState"),
                order_id=data.get("orderId", ""),
                auto_renewing=data.get("autoRenewing"),
                expiry_time_millis=int(data.get("expiryTimeMillis", 0)) if data.get("expiryTimeMillis") else None
            )

            # Check if purchase is valid (payment state 1 = paid)
            if verification.purchase_state != 1:
                logger.warning(
                    "google_subscription_not_paid",
                    purchase_state=verification.purchase_state
                )
                return None

            # Convert to VerifiedReceipt
            verified = self._convert_subscription_to_verified_receipt(verification)

            logger.info(
                "google_subscription_verified",
                product_id=verified.product_id,
                order_id=verification.order_id
            )

            return verified

        except Exception as e:
            logger.error("google_subscription_verification_error", error=str(e))
            raise

    async def verify_product(
        self,
        package_name: str,
        product_id: str,
        purchase_token: str
    ) -> Optional[VerifiedReceipt]:
        """
        Verify a Google Play one-time product purchase.

        Args:
            package_name: Android app package name
            product_id: Product ID
            purchase_token: Purchase token from Google Play

        Returns:
            VerifiedReceipt if valid, None if invalid
        """
        try:
            # Get access token
            credentials = self._get_credentials()
            credentials.refresh(Request())
            access_token = credentials.token

            # Call Google Play API
            url = (
                f"{GOOGLE_PLAY_API_BASE}/applications/{package_name}/"
                f"purchases/products/{product_id}/tokens/{purchase_token}"
            )

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=30.0
                )

                response.raise_for_status()
                data = response.json()

            # Parse response
            verification = GoogleVerificationResponse(
                kind=data.get("kind", ""),
                purchase_token=purchase_token,
                product_id=product_id,
                purchase_time_millis=int(data.get("purchaseTimeMillis", 0)),
                purchase_state=data.get("purchaseState"),
                acknowledgement_state=data.get("acknowledgementState"),
                order_id=data.get("orderId", ""),
                auto_renewing=None,  # One-time purchases don't auto-renew
                expiry_time_millis=None  # One-time purchases don't expire
            )

            # Check if purchase is valid (purchase state 0 = purchased)
            if verification.purchase_state != 0:
                logger.warning(
                    "google_product_not_purchased",
                    purchase_state=verification.purchase_state
                )
                return None

            # Convert to VerifiedReceipt
            verified = self._convert_product_to_verified_receipt(verification)

            logger.info(
                "google_product_verified",
                product_id=verified.product_id,
                order_id=verification.order_id
            )

            return verified

        except Exception as e:
            logger.error("google_product_verification_error", error=str(e))
            raise

    def _convert_subscription_to_verified_receipt(
        self,
        verification: GoogleVerificationResponse
    ) -> VerifiedReceipt:
        """
        Convert Google subscription verification to VerifiedReceipt.

        Args:
            verification: Google verification response

        Returns:
            VerifiedReceipt
        """
        # Convert milliseconds to seconds
        purchase_date = verification.purchase_time_millis // 1000
        expires_at = verification.expiry_time_millis // 1000 if verification.expiry_time_millis else None

        return VerifiedReceipt(
            platform=ReceiptPlatform.ANDROID,
            product_id=verification.product_id,
            transaction_id=verification.order_id,
            original_transaction_id=verification.order_id,
            purchase_date=purchase_date,
            expires_at=expires_at,
            auto_renew=verification.auto_renewing or False,
            is_subscription=True,
            environment="production"
        )

    def _convert_product_to_verified_receipt(
        self,
        verification: GoogleVerificationResponse
    ) -> VerifiedReceipt:
        """
        Convert Google product verification to VerifiedReceipt.

        Args:
            verification: Google verification response

        Returns:
            VerifiedReceipt
        """
        # Convert milliseconds to seconds
        purchase_date = verification.purchase_time_millis // 1000

        return VerifiedReceipt(
            platform=ReceiptPlatform.ANDROID,
            product_id=verification.product_id,
            transaction_id=verification.order_id,
            original_transaction_id=verification.order_id,
            purchase_date=purchase_date,
            expires_at=None,  # One-time purchases don't expire
            auto_renew=False,
            is_subscription=False,
            environment="production"
        )
