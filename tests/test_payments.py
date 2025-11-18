"""
Tests for payment verification module.

Tests receipt verification, add-on activation, and webhook handling.
"""
import pytest
import os
from unittest.mock import Mock, AsyncMock, patch
from fastapi import HTTPException

# Set required environment variables for tests
os.environ.setdefault("TURSO_ORG_URL", "test.turso.io")
os.environ.setdefault("TURSO_AUTH_TOKEN", "test_token")
os.environ.setdefault("JWT_SECRET", "test_jwt_secret_for_testing_only")

from app.payments.models import (
    VerifyReceiptRequest,
    VerifyReceiptResponse,
    VerificationStatus,
    ReceiptPlatform,
    VerifiedReceipt
)
from app.payments.service import PaymentService
from app.payments.verifiers.apple_verifier import AppleReceiptVerifier
from app.add_ons.models import AddOnType, Platform


# ========== Fixtures ==========

@pytest.fixture
def mock_master_db():
    """Mock master database manager."""
    mock_db = Mock()
    mock_db.get_connection.return_value = Mock()
    return mock_db


@pytest.fixture
def mock_add_ons_service():
    """Mock add-ons service."""
    return Mock()


@pytest.fixture
def payment_service(mock_master_db, mock_add_ons_service):
    """Create payment service with mocked dependencies."""
    return PaymentService(mock_master_db, mock_add_ons_service)


@pytest.fixture
def verified_sync_subscription():
    """Mock verified Sync subscription receipt."""
    return VerifiedReceipt(
        platform=ReceiptPlatform.IOS,
        product_id="echolia.sync.monthly",
        transaction_id="txn_sync_123",
        original_transaction_id="orig_txn_sync_123",
        purchase_date=1700000000,
        expires_at=1702592000,  # Future date
        auto_renew=True,
        is_subscription=True,
        environment="production"
    )


@pytest.fixture
def verified_ai_subscription():
    """Mock verified AI subscription receipt."""
    return VerifiedReceipt(
        platform=ReceiptPlatform.ANDROID,
        product_id="echolia.ai.monthly",
        transaction_id="txn_ai_123",
        original_transaction_id="orig_txn_ai_123",
        purchase_date=1700000000,
        expires_at=1702592000,
        auto_renew=True,
        is_subscription=True,
        environment="production"
    )


@pytest.fixture
def verified_supporter_purchase():
    """Mock verified supporter one-time purchase."""
    return VerifiedReceipt(
        platform=ReceiptPlatform.IOS,
        product_id="echolia.support.small",
        transaction_id="txn_support_123",
        original_transaction_id="txn_support_123",
        purchase_date=1700000000,
        expires_at=None,  # One-time purchases don't expire
        auto_renew=False,
        is_subscription=False,
        environment="production"
    )


# ========== Service Tests ==========

@pytest.mark.asyncio
async def test_verify_and_activate_ios_sync_subscription(
    payment_service,
    mock_master_db,
    mock_add_ons_service,
    verified_sync_subscription
):
    """Test verifying iOS Sync subscription and activating add-on."""
    # Mock Apple verification
    payment_service.apple_verifier = AsyncMock()
    payment_service.apple_verifier.verify_receipt = AsyncMock(
        return_value=verified_sync_subscription
    )

    # Mock receipt not already verified
    mock_master_db.get_connection.return_value.execute.return_value.rows = []

    # Mock add-on activation
    mock_add_ons_service.activate_add_on.return_value = True

    # Create request
    request = VerifyReceiptRequest(
        platform=ReceiptPlatform.IOS,
        receipt_data="base64_encoded_receipt",
        product_id="echolia.sync.monthly"
    )

    # Verify and activate
    result = await payment_service.verify_and_activate("user_123", request)

    # Assertions
    assert result.status == VerificationStatus.VERIFIED
    assert result.add_on_type == "sync"
    assert result.is_subscription is True
    assert result.expires_at == 1702592000
    assert result.transaction_id == "txn_sync_123"

    # Verify add-on was activated
    mock_add_ons_service.activate_add_on.assert_called_once()
    call_args = mock_add_ons_service.activate_add_on.call_args[1]
    assert call_args["user_id"] == "user_123"
    assert call_args["add_on_type"] == AddOnType.SYNC
    assert call_args["platform"] == Platform.IOS


@pytest.mark.asyncio
async def test_verify_and_activate_android_ai_subscription(
    payment_service,
    mock_master_db,
    mock_add_ons_service,
    verified_ai_subscription
):
    """Test verifying Android AI subscription and activating add-on."""
    # Mock Google verification
    payment_service.google_verifier = AsyncMock()
    payment_service.google_verifier.verify_subscription = AsyncMock(
        return_value=verified_ai_subscription
    )

    # Mock receipt not already verified
    mock_master_db.get_connection.return_value.execute.return_value.rows = []

    # Mock add-on activation
    mock_add_ons_service.activate_add_on.return_value = True

    # Create request
    request = VerifyReceiptRequest(
        platform=ReceiptPlatform.ANDROID,
        receipt_data="purchase_token_from_google",
        product_id="echolia.ai.monthly"
    )

    # Verify and activate
    result = await payment_service.verify_and_activate("user_123", request)

    # Assertions
    assert result.status == VerificationStatus.VERIFIED
    assert result.add_on_type == "ai"
    assert result.is_subscription is True

    # Verify add-on was activated with correct platform
    call_args = mock_add_ons_service.activate_add_on.call_args[1]
    assert call_args["platform"] == Platform.ANDROID


@pytest.mark.asyncio
async def test_verify_and_activate_supporter_purchase(
    payment_service,
    mock_master_db,
    mock_add_ons_service,
    verified_supporter_purchase
):
    """Test verifying supporter one-time purchase."""
    # Mock Apple verification
    payment_service.apple_verifier = AsyncMock()
    payment_service.apple_verifier.verify_receipt = AsyncMock(
        return_value=verified_supporter_purchase
    )

    # Mock receipt not already verified
    mock_master_db.get_connection.return_value.execute.return_value.rows = []

    # Mock add-on activation
    mock_add_ons_service.activate_add_on.return_value = True

    # Create request
    request = VerifyReceiptRequest(
        platform=ReceiptPlatform.IOS,
        receipt_data="base64_encoded_receipt",
        product_id="echolia.support.small"
    )

    # Verify and activate
    result = await payment_service.verify_and_activate("user_123", request)

    # Assertions
    assert result.status == VerificationStatus.VERIFIED
    assert result.add_on_type == "supporter"
    assert result.is_subscription is False
    assert result.expires_at is None  # One-time purchases don't expire

    # Verify add-on was activated
    call_args = mock_add_ons_service.activate_add_on.call_args[1]
    assert call_args["add_on_type"] == AddOnType.SUPPORTER
    assert call_args["expires_at"] is None


@pytest.mark.asyncio
async def test_verify_invalid_receipt(payment_service, mock_master_db, mock_add_ons_service):
    """Test handling of invalid receipt."""
    # Mock Apple verification returning None (invalid)
    payment_service.apple_verifier = AsyncMock()
    payment_service.apple_verifier.verify_receipt = AsyncMock(return_value=None)

    # Create request
    request = VerifyReceiptRequest(
        platform=ReceiptPlatform.IOS,
        receipt_data="invalid_receipt",
        product_id="echolia.sync.monthly"
    )

    # Verify
    result = await payment_service.verify_and_activate("user_123", request)

    # Assertions
    assert result.status == VerificationStatus.INVALID
    assert "verification failed" in result.message.lower()

    # Verify add-on was NOT activated
    mock_add_ons_service.activate_add_on.assert_not_called()


@pytest.mark.asyncio
async def test_verify_already_verified_receipt(
    payment_service,
    mock_master_db,
    mock_add_ons_service,
    verified_sync_subscription
):
    """Test handling of already verified receipt (replay attack prevention)."""
    # Mock Apple verification
    payment_service.apple_verifier = AsyncMock()
    payment_service.apple_verifier.verify_receipt = AsyncMock(
        return_value=verified_sync_subscription
    )

    # Mock receipt already exists in database
    mock_result = Mock()
    mock_result.rows = [("receipt_id_123",)]
    mock_master_db.get_connection.return_value.execute.return_value = mock_result

    # Create request
    request = VerifyReceiptRequest(
        platform=ReceiptPlatform.IOS,
        receipt_data="base64_encoded_receipt",
        product_id="echolia.sync.monthly"
    )

    # Verify
    result = await payment_service.verify_and_activate("user_123", request)

    # Assertions
    assert result.status == VerificationStatus.ALREADY_VERIFIED
    assert "already been processed" in result.message

    # Verify add-on was NOT activated (duplicate)
    mock_add_ons_service.activate_add_on.assert_not_called()


@pytest.mark.asyncio
async def test_verify_unknown_product_id(payment_service, mock_master_db, mock_add_ons_service):
    """Test handling of unknown product ID."""
    # Mock Apple verifier to track calls
    payment_service.apple_verifier = AsyncMock()
    payment_service.apple_verifier.verify_receipt = AsyncMock()

    # Create request with unknown product
    request = VerifyReceiptRequest(
        platform=ReceiptPlatform.IOS,
        receipt_data="base64_encoded_receipt",
        product_id="unknown.product.id"
    )

    # Verify
    result = await payment_service.verify_and_activate("user_123", request)

    # Assertions
    assert result.status == VerificationStatus.INVALID
    assert "unknown product id" in result.message.lower()

    # Verify Apple was NOT called (early return on unknown product)
    payment_service.apple_verifier.verify_receipt.assert_not_called()


@pytest.mark.asyncio
async def test_verify_add_on_activation_fails(
    payment_service,
    mock_master_db,
    mock_add_ons_service,
    verified_sync_subscription
):
    """Test handling when add-on activation fails."""
    # Mock Apple verification
    payment_service.apple_verifier = AsyncMock()
    payment_service.apple_verifier.verify_receipt = AsyncMock(
        return_value=verified_sync_subscription
    )

    # Mock receipt not already verified
    mock_master_db.get_connection.return_value.execute.return_value.rows = []

    # Mock add-on activation failing
    mock_add_ons_service.activate_add_on.return_value = False

    # Create request
    request = VerifyReceiptRequest(
        platform=ReceiptPlatform.IOS,
        receipt_data="base64_encoded_receipt",
        product_id="echolia.sync.monthly"
    )

    # Verify
    result = await payment_service.verify_and_activate("user_123", request)

    # Assertions
    assert result.status == VerificationStatus.ERROR
    assert "failed to activate" in result.message.lower()
