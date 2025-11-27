"""
Payment verification service.

Handles receipt verification and add-on activation.
"""
import structlog
import uuid
import time
from typing import Optional

from app.payments.models import (
    VerifyReceiptRequest,
    VerifyReceiptResponse,
    VerificationStatus,
    ReceiptPlatform,
    VerifiedReceipt
)
from app.payments.verifiers.apple_verifier import AppleReceiptVerifier
from app.payments.verifiers.google_verifier import GoogleReceiptVerifier
from app.add_ons.models import AddOnType, Platform, get_add_on_type_from_product_id
from app.add_ons.service import AddOnsService
from app.master_db import MasterDatabaseManager


logger = structlog.get_logger()


# Package name for Android app (would be configured in production)
ANDROID_PACKAGE_NAME = "com.echolia.app"


class PaymentService:
    """
    Service for verifying purchase receipts and activating add-ons.

    Supports both App Store and Play Store receipt verification.
    """

    def __init__(
        self,
        master_db: MasterDatabaseManager,
        add_ons_service: AddOnsService
    ):
        """
        Initialize payment service.

        Args:
            master_db: Master database manager
            add_ons_service: Add-ons service
        """
        self.master_db = master_db
        self.add_ons_service = add_ons_service
        self.apple_verifier = AppleReceiptVerifier()
        self.google_verifier = GoogleReceiptVerifier()

    async def verify_and_activate(
        self,
        user_id: str,
        request: VerifyReceiptRequest
    ) -> VerifyReceiptResponse:
        """
        Verify a purchase receipt and activate the add-on.

        Args:
            user_id: User UUID
            request: Receipt verification request

        Returns:
            VerifyReceiptResponse with verification status
        """
        try:
            # Determine add-on type from product ID
            add_on_type = get_add_on_type_from_product_id(request.product_id)

            if not add_on_type:
                logger.warning(
                    "unknown_product_id",
                    product_id=request.product_id
                )
                return VerifyReceiptResponse(
                    status=VerificationStatus.INVALID,
                    message=f"Unknown product ID: {request.product_id}"
                )

            # Verify receipt based on platform
            if request.platform == ReceiptPlatform.IOS:
                verified = await self._verify_apple_receipt(request)
            elif request.platform == ReceiptPlatform.ANDROID:
                verified = await self._verify_google_receipt(request)
            else:
                return VerifyReceiptResponse(
                    status=VerificationStatus.INVALID,
                    message="Invalid platform"
                )

            if not verified:
                return VerifyReceiptResponse(
                    status=VerificationStatus.INVALID,
                    message="Receipt verification failed"
                )

            # Check if receipt was already verified (prevent replay attacks)
            if self._is_receipt_already_verified(verified.transaction_id):
                logger.warning(
                    "receipt_already_verified",
                    transaction_id=verified.transaction_id
                )
                return VerifyReceiptResponse(
                    status=VerificationStatus.ALREADY_VERIFIED,
                    message="Receipt has already been processed",
                    transaction_id=verified.transaction_id
                )

            # Store receipt in database
            self._store_receipt(user_id, verified)

            # Activate add-on
            platform = Platform.IOS if verified.platform == ReceiptPlatform.IOS else Platform.ANDROID

            success = self.add_ons_service.activate_add_on(
                user_id=user_id,
                add_on_type=add_on_type,
                platform=platform,
                product_id=verified.product_id,
                transaction_id=verified.transaction_id,
                original_transaction_id=verified.original_transaction_id,
                purchase_date=verified.purchase_date,
                expires_at=verified.expires_at,
                auto_renew=verified.auto_renew
            )

            if not success:
                logger.error("add_on_activation_failed", user_id=user_id)
                return VerifyReceiptResponse(
                    status=VerificationStatus.ERROR,
                    message="Failed to activate add-on"
                )

            logger.info(
                "receipt_verified_and_addon_activated",
                user_id=user_id,
                add_on_type=add_on_type.value,
                transaction_id=verified.transaction_id
            )

            return VerifyReceiptResponse(
                status=VerificationStatus.VERIFIED,
                message="Purchase verified and add-on activated",
                add_on_type=add_on_type.value,
                expires_at=verified.expires_at,
                transaction_id=verified.transaction_id,
                is_subscription=verified.is_subscription
            )

        except Exception as e:
            logger.error("verify_and_activate_error", user_id=user_id, error=str(e))
            return VerifyReceiptResponse(
                status=VerificationStatus.ERROR,
                message=f"Verification error: {str(e)}"
            )

    async def _verify_apple_receipt(
        self,
        request: VerifyReceiptRequest
    ) -> Optional[VerifiedReceipt]:
        """
        Verify Apple App Store receipt.

        Args:
            request: Receipt verification request

        Returns:
            VerifiedReceipt or None
        """
        try:
            verified = await self.apple_verifier.verify_receipt(request.receipt_data)
            return verified

        except Exception as e:
            logger.error("apple_receipt_verification_failed", error=str(e))
            return None

    async def _verify_google_receipt(
        self,
        request: VerifyReceiptRequest
    ) -> Optional[VerifiedReceipt]:
        """
        Verify Google Play Store receipt.

        The receipt_data for Google contains the purchase token.

        Args:
            request: Receipt verification request

        Returns:
            VerifiedReceipt or None
        """
        try:
            purchase_token = request.receipt_data

            # Determine if subscription or one-time product
            # Subscriptions have .monthly in product ID
            is_subscription = ".monthly" in request.product_id or "subscription" in request.product_id.lower()

            if is_subscription:
                verified = await self.google_verifier.verify_subscription(
                    package_name=ANDROID_PACKAGE_NAME,
                    subscription_id=request.product_id,
                    purchase_token=purchase_token
                )
            else:
                verified = await self.google_verifier.verify_product(
                    package_name=ANDROID_PACKAGE_NAME,
                    product_id=request.product_id,
                    purchase_token=purchase_token
                )

            return verified

        except Exception as e:
            logger.error("google_receipt_verification_failed", error=str(e))
            return None

    def _is_receipt_already_verified(self, transaction_id: str) -> bool:
        """
        Check if receipt was already verified.

        Args:
            transaction_id: Transaction ID

        Returns:
            True if already verified
        """
        try:
            conn = self.master_db.get_connection()

            result = conn.execute(
                "SELECT id FROM receipts WHERE transaction_id = ? LIMIT 1",
                [transaction_id]
            )

            rows = result.fetchall()
            return len(rows) > 0

        except Exception as e:
            logger.error("check_receipt_duplicate_error", error=str(e))
            return False

    def _store_receipt(self, user_id: str, verified: VerifiedReceipt) -> bool:
        """
        Store verified receipt in database.

        Args:
            user_id: User UUID
            verified: Verified receipt information

        Returns:
            True if stored successfully
        """
        try:
            conn = self.master_db.get_connection()

            receipt_id = str(uuid.uuid4())
            current_time = int(time.time())

            conn.execute(
                """
                INSERT INTO receipts (id, user_id, platform, receipt_data, product_id, transaction_id, verified_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    receipt_id,
                    user_id,
                    verified.platform.value,
                    verified.transaction_id,  # Store transaction ID as receipt data
                    verified.product_id,
                    verified.transaction_id,
                    current_time
                ]
            )
            conn.commit()

            logger.info("receipt_stored", receipt_id=receipt_id, user_id=user_id)
            return True

        except Exception as e:
            logger.error("store_receipt_error", user_id=user_id, error=str(e))
            return False
