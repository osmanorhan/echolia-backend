"""
Payment verification models and schemas.

Handles App Store and Play Store receipt verification.
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from enum import Enum


# ========== Enums ==========

class ReceiptPlatform(str, Enum):
    """Receipt platform."""
    IOS = "ios"
    ANDROID = "android"


class VerificationStatus(str, Enum):
    """Receipt verification status."""
    VERIFIED = "verified"
    INVALID = "invalid"
    EXPIRED = "expired"
    ALREADY_VERIFIED = "already_verified"
    ERROR = "error"


# ========== Receipt Verification Request ==========

class VerifyReceiptRequest(BaseModel):
    """Request to verify a purchase receipt."""
    platform: ReceiptPlatform = Field(
        description="Purchase platform (ios or android)"
    )
    receipt_data: str = Field(
        description="Base64-encoded receipt data from App Store or Play Store"
    )
    product_id: str = Field(
        description="Product ID being purchased"
    )
    transaction_id: Optional[str] = Field(
        default=None,
        description="Transaction ID (optional, for client validation)"
    )


# ========== Receipt Verification Response ==========

class VerifyReceiptResponse(BaseModel):
    """Response from receipt verification."""
    status: VerificationStatus
    message: str
    add_on_type: Optional[str] = None
    expires_at: Optional[int] = None
    transaction_id: Optional[str] = None
    is_subscription: bool = False


# ========== Apple Receipt Models ==========

class AppleReceiptInfo(BaseModel):
    """Apple receipt information from verification."""
    product_id: str
    transaction_id: str
    original_transaction_id: str
    purchase_date_ms: int
    expires_date_ms: Optional[int] = None
    is_trial_period: bool = False
    is_in_intro_offer_period: bool = False
    cancellation_date_ms: Optional[int] = None
    auto_renew_status: Optional[bool] = None


class AppleVerificationResponse(BaseModel):
    """Apple App Store Server API response."""
    status: int
    environment: str
    receipt: Optional[Dict[str, Any]] = None
    latest_receipt_info: Optional[list] = None
    pending_renewal_info: Optional[list] = None
    is_retryable: bool = False


# ========== Google Receipt Models ==========

class GoogleReceiptInfo(BaseModel):
    """Google Play receipt information from verification."""
    product_id: str
    purchase_token: str
    purchase_time_millis: int
    expiry_time_millis: Optional[int] = None
    auto_renewing: Optional[bool] = None
    order_id: str
    acknowledgement_state: Optional[int] = None
    purchase_state: Optional[int] = None


class GoogleVerificationResponse(BaseModel):
    """Google Play Developer API response."""
    kind: str
    purchase_token: str
    product_id: str
    purchase_time_millis: int
    purchase_state: Optional[int] = None
    acknowledgement_state: Optional[int] = None
    order_id: str
    auto_renewing: Optional[bool] = None
    expiry_time_millis: Optional[int] = None


# ========== Webhook Models ==========

class AppleWebhookNotification(BaseModel):
    """Apple App Store Server Notification."""
    notification_type: str
    password: Optional[str] = None
    environment: str
    unified_receipt: Optional[Dict[str, Any]] = None
    latest_receipt: Optional[str] = None
    latest_receipt_info: Optional[list] = None
    auto_renew_product_id: Optional[str] = None
    auto_renew_status: Optional[str] = None


class GoogleWebhookNotification(BaseModel):
    """Google Play Developer Notification."""
    version: str
    package_name: str
    event_time_millis: int
    subscription_notification: Optional[Dict[str, Any]] = None
    one_time_product_notification: Optional[Dict[str, Any]] = None
    test_notification: Optional[Dict[str, Any]] = None


# ========== Internal Models ==========

class VerifiedReceipt(BaseModel):
    """Verified receipt information (internal use)."""
    platform: ReceiptPlatform
    product_id: str
    transaction_id: str
    original_transaction_id: Optional[str] = None
    purchase_date: int  # Unix timestamp in seconds
    expires_at: Optional[int] = None  # Unix timestamp in seconds
    auto_renew: bool = False
    is_subscription: bool = False
    environment: str = "production"


class WebhookProcessingResult(BaseModel):
    """Result of webhook processing."""
    success: bool
    message: str
    user_id: Optional[str] = None
    add_on_type: Optional[str] = None
    action: Optional[str] = None  # "renewed", "cancelled", "expired"
