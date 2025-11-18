"""
Add-ons service - Business logic for add-on management.

Provides a service layer on top of master database add-on operations.
"""
import structlog
from typing import Optional

from app.add_ons.models import (
    AddOnType,
    AddOnStatus,
    AddOnDetail,
    AddOnsStatusResponse,
    FeatureFlags,
    FeatureFlagsResponse,
    Platform
)
from app.master_db import MasterDatabaseManager


logger = structlog.get_logger()


class AddOnsService:
    """
    Service for managing user add-ons and feature flags.

    This service wraps master database add-on operations and provides
    business logic for feature flag generation and add-on status checks.
    """

    def __init__(self, master_db: MasterDatabaseManager):
        """
        Initialize add-ons service.

        Args:
            master_db: Master database manager instance
        """
        self.master_db = master_db

    def get_add_ons_status(self, user_id: str) -> AddOnsStatusResponse:
        """
        Get detailed add-ons status for a user.

        Args:
            user_id: User UUID

        Returns:
            AddOnsStatusResponse with flags and detailed add-on info
        """
        try:
            # Get add-ons from master database
            add_ons_data = self.master_db.get_user_add_ons(user_id)

            # Convert details to AddOnDetail models
            details = []
            for detail in add_ons_data.get("details", []):
                details.append(AddOnDetail(
                    add_on_type=AddOnType(detail["add_on_type"]),
                    status=AddOnStatus(detail["status"]),
                    platform=Platform(detail["platform"]),
                    product_id=detail["product_id"],
                    transaction_id=detail["transaction_id"],
                    purchase_date=detail["purchase_date"],
                    expires_at=detail.get("expires_at"),
                    auto_renew=detail.get("auto_renew", False),
                    cancelled_at=detail.get("cancelled_at"),
                    is_active=detail["is_active"]
                ))

            return AddOnsStatusResponse(
                sync_enabled=add_ons_data.get("sync_enabled", False),
                ai_enabled=add_ons_data.get("ai_enabled", False),
                supporter=add_ons_data.get("supporter", False),
                details=details
            )

        except Exception as e:
            logger.error("get_add_ons_status_failed", user_id=user_id, error=str(e))
            raise

    def get_feature_flags(self, user_id: str) -> FeatureFlagsResponse:
        """
        Get feature flags for a user based on active add-ons.

        Args:
            user_id: User UUID

        Returns:
            FeatureFlagsResponse with feature flags
        """
        try:
            # Get add-ons from master database
            add_ons_data = self.master_db.get_user_add_ons(user_id)

            # Build feature flags
            flags = FeatureFlags(
                sync_enabled=add_ons_data.get("sync_enabled", False),
                ai_enabled=add_ons_data.get("ai_enabled", False),
                supporter=add_ons_data.get("supporter", False)
            )

            return FeatureFlagsResponse(
                flags=flags,
                user_id=user_id
            )

        except Exception as e:
            logger.error("get_feature_flags_failed", user_id=user_id, error=str(e))
            raise

    def is_add_on_active(self, user_id: str, add_on_type: AddOnType) -> bool:
        """
        Check if a specific add-on is active for a user.

        Args:
            user_id: User UUID
            add_on_type: Type of add-on to check

        Returns:
            True if add-on is active
        """
        try:
            return self.master_db.is_add_on_active(user_id, add_on_type.value)

        except Exception as e:
            logger.error(
                "is_add_on_active_check_failed",
                user_id=user_id,
                add_on_type=add_on_type.value,
                error=str(e)
            )
            return False

    def activate_add_on(
        self,
        user_id: str,
        add_on_type: AddOnType,
        platform: Platform,
        product_id: str,
        transaction_id: str,
        original_transaction_id: Optional[str],
        purchase_date: int,
        expires_at: Optional[int],
        auto_renew: bool
    ) -> bool:
        """
        Activate an add-on after purchase verification.

        This method should be called from the payments service
        after successfully verifying a receipt.

        Args:
            user_id: User UUID
            add_on_type: Type of add-on (sync, ai, supporter)
            platform: Purchase platform (ios, android)
            product_id: Store product ID
            transaction_id: Store transaction ID
            original_transaction_id: Original transaction ID (for subscriptions)
            purchase_date: Purchase timestamp
            expires_at: Expiration timestamp (None for one-time purchases)
            auto_renew: Whether auto-renewal is enabled

        Returns:
            True if activated successfully
        """
        try:
            return self.master_db.activate_add_on(
                user_id=user_id,
                add_on_type=add_on_type.value,
                platform=platform.value,
                product_id=product_id,
                transaction_id=transaction_id,
                original_transaction_id=original_transaction_id,
                purchase_date=purchase_date,
                expires_at=expires_at,
                auto_renew=auto_renew
            )

        except Exception as e:
            logger.error(
                "activate_add_on_failed",
                user_id=user_id,
                add_on_type=add_on_type.value,
                error=str(e)
            )
            raise
