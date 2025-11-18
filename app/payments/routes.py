"""
Payment verification API routes.

Handles receipt verification and webhook notifications.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from typing import Tuple
import structlog

from app.payments.models import (
    VerifyReceiptRequest,
    VerifyReceiptResponse,
    VerificationStatus
)
from app.payments.service import PaymentService
from app.auth.dependencies import get_current_user
from app.master_db import get_master_db_manager, MasterDatabaseManager
from app.add_ons.service import AddOnsService


logger = structlog.get_logger()
router = APIRouter(prefix="/payments", tags=["payments"])


def get_payment_service(
    master_db: MasterDatabaseManager = Depends(get_master_db_manager)
) -> PaymentService:
    """Dependency to get payment service."""
    add_ons_service = AddOnsService(master_db)
    return PaymentService(master_db, add_ons_service)


# ========== Receipt Verification ==========

@router.post("/verify", response_model=VerifyReceiptResponse)
async def verify_receipt(
    request: VerifyReceiptRequest,
    current_user: Tuple[str, str] = Depends(get_current_user),
    payment_service: PaymentService = Depends(get_payment_service)
):
    """
    Verify a purchase receipt and activate add-on.

    This endpoint verifies receipts from both App Store and Play Store,
    then activates the corresponding add-on for the user.

    **Supported Platforms:**
    - iOS: App Store receipts (base64-encoded)
    - Android: Play Store purchase tokens

    **Supported Products:**
    - `echolia.sync.monthly` - Sync Add-on ($2/month)
    - `echolia.ai.monthly` - AI Add-on ($3/month)
    - `echolia.support.{small,medium,large}` - Supporter tiers

    **Flow:**
    1. Client makes purchase via App Store / Play Store
    2. Client receives receipt / purchase token
    3. Client sends receipt to this endpoint
    4. Server verifies with Apple / Google
    5. Server activates add-on if valid
    6. Client receives confirmation

    **Security:**
    - Prevents replay attacks (duplicate receipt check)
    - Verifies directly with App Store / Play Store APIs
    - Requires authentication

    **Errors:**
    - 400: Invalid request
    - 401: Unauthorized
    - 200 with status "invalid": Receipt verification failed
    - 200 with status "already_verified": Receipt already processed
    """
    user_id, _ = current_user

    try:
        result = await payment_service.verify_and_activate(user_id, request)

        # Log verification attempt
        logger.info(
            "payment_verification_attempt",
            user_id=user_id,
            platform=request.platform.value,
            product_id=request.product_id,
            status=result.status.value
        )

        return result

    except Exception as e:
        logger.error("payment_verification_error", user_id=user_id, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Payment verification failed"
        )


# ========== Webhooks ==========

@router.post("/webhook/apple")
async def apple_webhook(request: Request):
    """
    Handle Apple App Store Server Notifications.

    Apple sends webhook notifications for subscription events:
    - INITIAL_BUY: New subscription
    - CANCEL: Subscription cancelled
    - DID_RENEW: Subscription renewed
    - DID_FAIL_TO_RENEW: Renewal failed
    - DID_CHANGE_RENEWAL_STATUS: Auto-renewal toggled

    This endpoint is called by Apple's servers directly.
    No authentication required (verified via shared secret).

    **Security:**
    - Verifies notification authenticity
    - Validates shared secret

    **Note:** Implementation pending - Phase 3.1
    """
    # TODO: Implement Apple webhook handler
    # 1. Parse notification
    # 2. Verify shared secret
    # 3. Handle different notification types
    # 4. Update add-on status in database
    logger.info("apple_webhook_received")
    return {"status": "received"}


@router.post("/webhook/google")
async def google_webhook(request: Request):
    """
    Handle Google Play Developer Notifications.

    Google sends webhook notifications for subscription events:
    - SUBSCRIPTION_RECOVERED: Subscription renewed after recovery
    - SUBSCRIPTION_RENEWED: Subscription renewed
    - SUBSCRIPTION_CANCELED: Subscription cancelled
    - SUBSCRIPTION_PURCHASED: New subscription
    - SUBSCRIPTION_ON_HOLD: Payment issue
    - SUBSCRIPTION_IN_GRACE_PERIOD: Grace period entered
    - SUBSCRIPTION_EXPIRED: Subscription expired

    This endpoint is called by Google's servers directly.
    Authentication via Pub/Sub verification.

    **Security:**
    - Verifies Pub/Sub message signature
    - Validates message authenticity

    **Note:** Implementation pending - Phase 3.1
    """
    # TODO: Implement Google webhook handler
    # 1. Verify Pub/Sub message
    # 2. Decode notification
    # 3. Handle different notification types
    # 4. Update add-on status in database
    logger.info("google_webhook_received")
    return {"status": "received"}
