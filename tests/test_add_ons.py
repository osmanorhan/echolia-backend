"""
Tests for add-ons module.

Tests add-on status, feature flags, and dependencies.
"""
import pytest
import os
from unittest.mock import Mock, MagicMock, patch
from fastapi import HTTPException

# Set required environment variables for tests
os.environ.setdefault("TURSO_ORG_URL", "test.turso.io")
os.environ.setdefault("TURSO_AUTH_TOKEN", "test_token")
os.environ.setdefault("JWT_SECRET", "test_jwt_secret_for_testing_only")

from app.add_ons.models import (
    AddOnType,
    AddOnStatus,
    Platform,
    AddOnDetail,
    FeatureFlags
)
from app.add_ons.service import AddOnsService
from app.add_ons.dependencies import (
    require_sync_addon,
    require_ai_addon,
    check_add_on,
    get_user_feature_flags
)


# ========== Fixtures ==========

@pytest.fixture
def mock_master_db():
    """Mock master database manager."""
    return Mock()


@pytest.fixture
def add_ons_service(mock_master_db):
    """Create add-ons service with mocked database."""
    return AddOnsService(mock_master_db)


@pytest.fixture
def mock_user_with_sync_addon():
    """Mock user add-ons data with active Sync add-on."""
    return {
        "sync_enabled": True,
        "ai_enabled": False,
        "supporter": False,
        "details": [
            {
                "add_on_type": "sync",
                "status": "active",
                "platform": "ios",
                "product_id": "echolia.sync.monthly",
                "transaction_id": "txn_123",
                "purchase_date": 1700000000,
                "expires_at": 1702592000,  # Future date
                "auto_renew": True,
                "cancelled_at": None,
                "is_active": True
            }
        ]
    }


@pytest.fixture
def mock_user_with_all_addons():
    """Mock user add-ons data with all add-ons active."""
    return {
        "sync_enabled": True,
        "ai_enabled": True,
        "supporter": True,
        "details": [
            {
                "add_on_type": "sync",
                "status": "active",
                "platform": "ios",
                "product_id": "echolia.sync.monthly",
                "transaction_id": "txn_sync",
                "purchase_date": 1700000000,
                "expires_at": 1702592000,
                "auto_renew": True,
                "cancelled_at": None,
                "is_active": True
            },
            {
                "add_on_type": "ai",
                "status": "active",
                "platform": "ios",
                "product_id": "echolia.ai.monthly",
                "transaction_id": "txn_ai",
                "purchase_date": 1700000000,
                "expires_at": 1702592000,
                "auto_renew": True,
                "cancelled_at": None,
                "is_active": True
            },
            {
                "add_on_type": "supporter",
                "status": "active",
                "platform": "ios",
                "product_id": "echolia.support.small",
                "transaction_id": "txn_support",
                "purchase_date": 1700000000,
                "expires_at": None,  # One-time purchase
                "auto_renew": False,
                "cancelled_at": None,
                "is_active": True
            }
        ]
    }


@pytest.fixture
def mock_user_no_addons():
    """Mock user add-ons data with no add-ons."""
    return {
        "sync_enabled": False,
        "ai_enabled": False,
        "supporter": False,
        "details": []
    }


# ========== Service Tests ==========

def test_get_add_ons_status_with_sync(add_ons_service, mock_master_db, mock_user_with_sync_addon):
    """Test getting add-ons status for user with Sync add-on."""
    mock_master_db.get_user_add_ons.return_value = mock_user_with_sync_addon

    result = add_ons_service.get_add_ons_status("user_123")

    assert result.sync_enabled is True
    assert result.ai_enabled is False
    assert result.supporter is False
    assert len(result.details) == 1
    assert result.details[0].add_on_type == AddOnType.SYNC
    assert result.details[0].status == AddOnStatus.ACTIVE
    assert result.details[0].platform == Platform.IOS
    assert result.details[0].is_active is True


def test_get_add_ons_status_with_all_addons(add_ons_service, mock_master_db, mock_user_with_all_addons):
    """Test getting add-ons status for user with all add-ons."""
    mock_master_db.get_user_add_ons.return_value = mock_user_with_all_addons

    result = add_ons_service.get_add_ons_status("user_123")

    assert result.sync_enabled is True
    assert result.ai_enabled is True
    assert result.supporter is True
    assert len(result.details) == 3


def test_get_add_ons_status_no_addons(add_ons_service, mock_master_db, mock_user_no_addons):
    """Test getting add-ons status for user with no add-ons."""
    mock_master_db.get_user_add_ons.return_value = mock_user_no_addons

    result = add_ons_service.get_add_ons_status("user_123")

    assert result.sync_enabled is False
    assert result.ai_enabled is False
    assert result.supporter is False
    assert len(result.details) == 0


def test_get_feature_flags(add_ons_service, mock_master_db, mock_user_with_all_addons):
    """Test getting feature flags."""
    mock_master_db.get_user_add_ons.return_value = mock_user_with_all_addons

    result = add_ons_service.get_feature_flags("user_123")

    assert result.user_id == "user_123"
    assert result.flags.sync_enabled is True
    assert result.flags.ai_enabled is True
    assert result.flags.supporter is True


def test_is_add_on_active_sync(add_ons_service, mock_master_db):
    """Test checking if Sync add-on is active."""
    mock_master_db.is_add_on_active.return_value = True

    result = add_ons_service.is_add_on_active("user_123", AddOnType.SYNC)

    assert result is True
    mock_master_db.is_add_on_active.assert_called_once_with("user_123", "sync")


def test_is_add_on_active_not_active(add_ons_service, mock_master_db):
    """Test checking add-on when not active."""
    mock_master_db.is_add_on_active.return_value = False

    result = add_ons_service.is_add_on_active("user_123", AddOnType.AI)

    assert result is False


def test_activate_add_on(add_ons_service, mock_master_db):
    """Test activating an add-on."""
    mock_master_db.activate_add_on.return_value = True

    result = add_ons_service.activate_add_on(
        user_id="user_123",
        add_on_type=AddOnType.SYNC,
        platform=Platform.IOS,
        product_id="echolia.sync.monthly",
        transaction_id="txn_123",
        original_transaction_id=None,
        purchase_date=1700000000,
        expires_at=1702592000,
        auto_renew=True
    )

    assert result is True
    mock_master_db.activate_add_on.assert_called_once()


# ========== Dependency Tests ==========

@pytest.mark.asyncio
async def test_require_sync_addon_with_active_addon():
    """Test require_sync_addon dependency when user has active Sync add-on."""
    mock_service = Mock()
    mock_service.is_add_on_active.return_value = True

    # Should not raise exception
    await require_sync_addon(
        current_user=("user_123", "device_123"),
        add_ons_service=mock_service
    )

    mock_service.is_add_on_active.assert_called_once_with("user_123", AddOnType.SYNC)


@pytest.mark.asyncio
async def test_require_sync_addon_without_addon():
    """Test require_sync_addon dependency when user doesn't have Sync add-on."""
    mock_service = Mock()
    mock_service.is_add_on_active.return_value = False

    # Should raise 403 HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await require_sync_addon(
            current_user=("user_123", "device_123"),
            add_ons_service=mock_service
        )

    assert exc_info.value.status_code == 403
    assert "Sync add-on required" in exc_info.value.detail


@pytest.mark.asyncio
async def test_require_ai_addon_with_active_addon():
    """Test require_ai_addon dependency when user has active AI add-on."""
    mock_service = Mock()
    mock_service.is_add_on_active.return_value = True

    # Should not raise exception
    await require_ai_addon(
        current_user=("user_123", "device_123"),
        add_ons_service=mock_service
    )

    mock_service.is_add_on_active.assert_called_once_with("user_123", AddOnType.AI)


@pytest.mark.asyncio
async def test_require_ai_addon_without_addon():
    """Test require_ai_addon dependency when user doesn't have AI add-on."""
    mock_service = Mock()
    mock_service.is_add_on_active.return_value = False

    # Should raise 403 HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await require_ai_addon(
            current_user=("user_123", "device_123"),
            add_ons_service=mock_service
        )

    assert exc_info.value.status_code == 403
    assert "AI add-on required" in exc_info.value.detail


@pytest.mark.asyncio
async def test_check_add_on_returns_bool():
    """Test check_add_on dependency returns boolean without raising."""
    mock_service = Mock()
    mock_service.is_add_on_active.return_value = True

    result = await check_add_on(
        add_on_type=AddOnType.SYNC,
        current_user=("user_123", "device_123"),
        add_ons_service=mock_service
    )

    assert result is True


@pytest.mark.asyncio
async def test_get_user_feature_flags_dependency():
    """Test get_user_feature_flags dependency."""
    mock_service = Mock()
    mock_flags_response = Mock()
    mock_flags_response.flags = FeatureFlags(
        sync_enabled=True,
        ai_enabled=False,
        supporter=False
    )
    mock_service.get_feature_flags.return_value = mock_flags_response

    result = await get_user_feature_flags(
        current_user=("user_123", "device_123"),
        add_ons_service=mock_service
    )

    assert isinstance(result, FeatureFlags)
    assert result.sync_enabled is True
    assert result.ai_enabled is False
    assert result.supporter is False
