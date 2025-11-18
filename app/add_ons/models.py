"""
Add-ons models and schemas.

Defines add-on types, statuses, and API response models.
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum


# ========== Enums ==========

class AddOnType(str, Enum):
    """Add-on subscription types."""
    SYNC = "sync"
    AI = "ai"
    SUPPORTER = "supporter"


class AddOnStatus(str, Enum):
    """Add-on subscription status."""
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class Platform(str, Enum):
    """Purchase platform."""
    IOS = "ios"
    ANDROID = "android"


# ========== Add-On Detail Models ==========

class AddOnDetail(BaseModel):
    """Detailed information about a user's add-on."""
    add_on_type: AddOnType
    status: AddOnStatus
    platform: Platform
    product_id: str
    transaction_id: str
    purchase_date: int
    expires_at: Optional[int] = None
    auto_renew: bool = False
    cancelled_at: Optional[int] = None
    is_active: bool = Field(
        description="True if status is active and not expired"
    )


# ========== Feature Flags ==========

class FeatureFlags(BaseModel):
    """Feature flags based on active add-ons."""
    sync_enabled: bool = Field(
        default=False,
        description="User has active Sync add-on"
    )
    ai_enabled: bool = Field(
        default=False,
        description="User has active AI add-on"
    )
    supporter: bool = Field(
        default=False,
        description="User has purchased Support Echolia"
    )


# ========== API Response Models ==========

class AddOnsStatusResponse(BaseModel):
    """Response for GET /add-ons/status endpoint."""
    sync_enabled: bool
    ai_enabled: bool
    supporter: bool
    details: List[AddOnDetail] = Field(
        description="Detailed information for each add-on"
    )


class FeatureFlagsResponse(BaseModel):
    """Response for GET /add-ons/features endpoint."""
    flags: FeatureFlags
    user_id: str


# ========== Product IDs ==========

# iOS and Android use the same product IDs
PRODUCT_IDS = {
    # Subscriptions
    "echolia.sync.monthly": AddOnType.SYNC,
    "echolia.ai.monthly": AddOnType.AI,

    # One-time purchases (supporter tier)
    "echolia.support.small": AddOnType.SUPPORTER,    # $5
    "echolia.support.medium": AddOnType.SUPPORTER,   # $10
    "echolia.support.large": AddOnType.SUPPORTER,    # $25
}


def get_add_on_type_from_product_id(product_id: str) -> Optional[AddOnType]:
    """
    Get add-on type from product ID.

    Args:
        product_id: Store product ID

    Returns:
        AddOnType or None if not found
    """
    return PRODUCT_IDS.get(product_id)
