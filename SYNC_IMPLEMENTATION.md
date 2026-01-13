# Echolia Backend - Sync Feature Implementation Plan

## Overview

This document provides step-by-step implementation guidance for the **backend sync feature**. The backend has **no dependencies** on mobile or desktop and should be developed first.

**Tech Stack**: FastAPI, Python 3.11+, Turso (LibSQL), Pydantic

**Root Plan**: See [../SYNC_IMPLEMENTATION_ROOT.md](../SYNC_IMPLEMENTATION_ROOT.md) for coordination details.

---

## Phase 1: Authentication + Payment Infrastructure (Week 1-2)

### Goal
Implement payment verification for App Store and Google Play receipts, plus entitlement middleware.

### 1.1 Create Payment Models

**File**: `app/payments/models.py`

```python
from pydantic import BaseModel, Field
from typing import Literal, Optional
from enum import Enum

class Platform(str, Enum):
    IOS = "ios"
    ANDROID = "android"

class VerifyReceiptRequest(BaseModel):
    platform: Platform
    receipt_data: str = Field(..., description="Base64-encoded receipt")
    product_id: str = Field(..., description="echolia.sync.monthly")

class VerifyReceiptResponse(BaseModel):
    status: Literal["success", "failed"]
    add_on_type: Optional[str] = None  # "sync", "ai", "supporter"
    expires_at: Optional[int] = None  # Unix timestamp
    transaction_id: Optional[str] = None
    original_transaction_id: Optional[str] = None
    error_message: Optional[str] = None

class AppleReceiptInfo(BaseModel):
    product_id: str
    transaction_id: str
    original_transaction_id: str
    purchase_date_ms: int
    expires_date_ms: Optional[int] = None
    auto_renew_status: Optional[int] = None
    cancellation_date_ms: Optional[int] = None

class GoogleReceiptInfo(BaseModel):
    product_id: str
    purchase_token: str
    purchase_time_millis: int
    expiry_time_millis: Optional[int] = None
    auto_renewing: Optional[bool] = None

class AppleWebhookNotification(BaseModel):
    notification_type: str
    latest_receipt_info: Optional[AppleReceiptInfo] = None
    auto_renew_status: Optional[int] = None

class GoogleWebhookNotification(BaseModel):
    subscription_notification: Optional[dict] = None
    one_time_product_notification: Optional[dict] = None
```

**Testing**: Run `pytest app/payments/test_models.py` (create tests)

---

### 1.2 Implement Apple Receipt Verifier

**File**: `app/payments/verifiers/apple_verifier.py`

```python
import httpx
import base64
import json
from typing import Tuple, Optional
from app.payments.models import AppleReceiptInfo
from app.config import get_settings

settings = get_settings()

class AppleReceiptVerifier:
    """
    Verifies Apple App Store receipts using App Store Server API.
    Supports both production and sandbox environments.
    """

    PRODUCTION_URL = "https://buy.itunes.apple.com/verifyReceipt"
    SANDBOX_URL = "https://sandbox.itunes.apple.com/verifyReceipt"

    def __init__(self, shared_secret: str):
        self.shared_secret = shared_secret

    async def verify(self, receipt_data: str) -> Tuple[bool, Optional[AppleReceiptInfo], Optional[str]]:
        """
        Verify an Apple receipt.

        Returns: (success, receipt_info, error_message)
        """
        # Try production first
        success, info, error = await self._verify_with_server(receipt_data, self.PRODUCTION_URL)

        # If production returns sandbox error, try sandbox
        if not success and error and "sandbox" in error.lower():
            success, info, error = await self._verify_with_server(receipt_data, self.SANDBOX_URL)

        return success, info, error

    async def _verify_with_server(
        self,
        receipt_data: str,
        url: str
    ) -> Tuple[bool, Optional[AppleReceiptInfo], Optional[str]]:
        payload = {
            "receipt-data": receipt_data,
            "password": self.shared_secret,
            "exclude-old-transactions": True
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    url,
                    json=payload,
                    timeout=10.0
                )
                response.raise_for_status()
                data = response.json()

                status = data.get("status")

                # Status codes: https://developer.apple.com/documentation/appstorereceipts/status
                if status == 0:  # Valid receipt
                    return self._parse_receipt(data)
                elif status == 21007:  # Sandbox receipt sent to production
                    return False, None, "Sandbox receipt in production environment"
                elif status == 21008:  # Production receipt sent to sandbox
                    return False, None, "Production receipt in sandbox environment"
                else:
                    return False, None, f"Apple verification failed with status {status}"

            except httpx.HTTPError as e:
                return False, None, f"HTTP error: {str(e)}"
            except Exception as e:
                return False, None, f"Verification error: {str(e)}"

    def _parse_receipt(self, data: dict) -> Tuple[bool, Optional[AppleReceiptInfo], Optional[str]]:
        """Parse Apple receipt response."""
        try:
            # For subscriptions, use latest_receipt_info
            latest_receipt_info = data.get("latest_receipt_info", [])
            if not latest_receipt_info:
                # For non-renewing purchases, use in_app
                latest_receipt_info = data.get("receipt", {}).get("in_app", [])

            if not latest_receipt_info:
                return False, None, "No receipt info found"

            # Get the most recent transaction
            receipt = latest_receipt_info[0]

            info = AppleReceiptInfo(
                product_id=receipt.get("product_id"),
                transaction_id=receipt.get("transaction_id"),
                original_transaction_id=receipt.get("original_transaction_id"),
                purchase_date_ms=int(receipt.get("purchase_date_ms")),
                expires_date_ms=int(receipt.get("expires_date_ms")) if receipt.get("expires_date_ms") else None,
                auto_renew_status=data.get("auto_renew_status"),
                cancellation_date_ms=int(receipt.get("cancellation_date_ms")) if receipt.get("cancellation_date_ms") else None
            )

            return True, info, None

        except Exception as e:
            return False, None, f"Failed to parse receipt: {str(e)}"
```

**Testing**: Create `app/payments/verifiers/test_apple_verifier.py` with mock responses

---

### 1.3 Implement Google Receipt Verifier

**File**: `app/payments/verifiers/google_verifier.py`

```python
from google.oauth2 import service_account
from googleapiclient.discovery import build
from typing import Tuple, Optional
from app.payments.models import GoogleReceiptInfo
from app.config import get_settings
import json

settings = get_settings()

class GoogleReceiptVerifier:
    """
    Verifies Google Play receipts using Google Play Developer API.
    """

    def __init__(self, service_account_json: str):
        """
        Args:
            service_account_json: JSON string of service account credentials
        """
        self.credentials = service_account.Credentials.from_service_account_info(
            json.loads(service_account_json),
            scopes=['https://www.googleapis.com/auth/androidpublisher']
        )
        self.service = build('androidpublisher', 'v3', credentials=self.credentials)

    async def verify_subscription(
        self,
        package_name: str,
        product_id: str,
        purchase_token: str
    ) -> Tuple[bool, Optional[GoogleReceiptInfo], Optional[str]]:
        """
        Verify a subscription purchase.

        Returns: (success, receipt_info, error_message)
        """
        try:
            result = self.service.purchases().subscriptions().get(
                packageName=package_name,
                subscriptionId=product_id,
                token=purchase_token
            ).execute()

            # Check if subscription is valid
            payment_state = result.get('paymentState')
            if payment_state != 1:  # 0 = pending, 1 = received, 2 = free trial, 3 = pending deferred
                return False, None, f"Invalid payment state: {payment_state}"

            info = GoogleReceiptInfo(
                product_id=product_id,
                purchase_token=purchase_token,
                purchase_time_millis=int(result.get('startTimeMillis')),
                expiry_time_millis=int(result.get('expiryTimeMillis')) if result.get('expiryTimeMillis') else None,
                auto_renewing=result.get('autoRenewing', False)
            )

            return True, info, None

        except Exception as e:
            return False, None, f"Google verification error: {str(e)}"

    async def verify_product(
        self,
        package_name: str,
        product_id: str,
        purchase_token: str
    ) -> Tuple[bool, Optional[GoogleReceiptInfo], Optional[str]]:
        """
        Verify a one-time product purchase.

        Returns: (success, receipt_info, error_message)
        """
        try:
            result = self.service.purchases().products().get(
                packageName=package_name,
                productId=product_id,
                token=purchase_token
            ).execute()

            # Check if product is valid
            purchase_state = result.get('purchaseState')
            if purchase_state != 0:  # 0 = purchased, 1 = canceled
                return False, None, f"Invalid purchase state: {purchase_state}"

            info = GoogleReceiptInfo(
                product_id=product_id,
                purchase_token=purchase_token,
                purchase_time_millis=int(result.get('purchaseTimeMillis')),
                expiry_time_millis=None,  # One-time purchases don't expire
                auto_renewing=False
            )

            return True, info, None

        except Exception as e:
            return False, None, f"Google verification error: {str(e)}"
```

**Testing**: Create `app/payments/verifiers/test_google_verifier.py` with mock API responses

---

### 1.4 Implement Payment Service

**File**: `app/payments/service.py`

```python
from app.payments.models import (
    VerifyReceiptRequest,
    VerifyReceiptResponse,
    Platform
)
from app.payments.verifiers.apple_verifier import AppleReceiptVerifier
from app.payments.verifiers.google_verifier import GoogleReceiptVerifier
from app.master_db import MasterDatabaseManager
from app.add_ons.models import AddOnType
from app.config import get_settings
import time

settings = get_settings()

class PaymentService:
    def __init__(
        self,
        master_db: MasterDatabaseManager,
        apple_verifier: AppleReceiptVerifier,
        google_verifier: GoogleReceiptVerifier
    ):
        self.master_db = master_db
        self.apple_verifier = apple_verifier
        self.google_verifier = google_verifier

    async def verify_and_store_receipt(
        self,
        user_id: str,
        request: VerifyReceiptRequest
    ) -> VerifyReceiptResponse:
        """
        Verify receipt with App Store/Google Play and store entitlement.
        """
        # Verify receipt
        if request.platform == Platform.IOS:
            success, info, error = await self.apple_verifier.verify(request.receipt_data)
        else:  # Android
            # Extract package name and token from receipt_data (base64 JSON)
            import base64
            import json
            try:
                decoded = base64.b64decode(request.receipt_data).decode('utf-8')
                receipt_info = json.loads(decoded)
                package_name = receipt_info.get('packageName', 'com.echolia.app')
                purchase_token = receipt_info.get('purchaseToken')

                # Determine if subscription or product
                if 'monthly' in request.product_id:
                    success, info, error = await self.google_verifier.verify_subscription(
                        package_name, request.product_id, purchase_token
                    )
                else:
                    success, info, error = await self.google_verifier.verify_product(
                        package_name, request.product_id, purchase_token
                    )
            except Exception as e:
                return VerifyReceiptResponse(
                    status="failed",
                    error_message=f"Invalid receipt format: {str(e)}"
                )

        if not success:
            return VerifyReceiptResponse(
                status="failed",
                error_message=error or "Verification failed"
            )

        # Determine add-on type from product ID
        add_on_type = self._get_add_on_type(request.product_id)
        if not add_on_type:
            return VerifyReceiptResponse(
                status="failed",
                error_message=f"Unknown product ID: {request.product_id}"
            )

        # Store in database
        try:
            # Store receipt
            self.master_db.store_receipt(
                user_id=user_id,
                platform=request.platform.value,
                receipt_data=request.receipt_data,
                product_id=request.product_id,
                transaction_id=info.transaction_id if hasattr(info, 'transaction_id') else info.purchase_token,
                verified_at=int(time.time())
            )

            # Update/create add-on entitlement
            expires_at = None
            if hasattr(info, 'expires_date_ms') and info.expires_date_ms:
                expires_at = info.expires_date_ms // 1000
            elif hasattr(info, 'expiry_time_millis') and info.expiry_time_millis:
                expires_at = info.expiry_time_millis // 1000

            self.master_db.upsert_user_add_on(
                user_id=user_id,
                add_on_type=add_on_type,
                status="active",
                platform=request.platform.value,
                product_id=request.product_id,
                transaction_id=info.transaction_id if hasattr(info, 'transaction_id') else info.purchase_token,
                original_transaction_id=info.original_transaction_id if hasattr(info, 'original_transaction_id') else None,
                purchase_date=info.purchase_date_ms // 1000 if hasattr(info, 'purchase_date_ms') else info.purchase_time_millis // 1000,
                expires_at=expires_at,
                auto_renew=info.auto_renew_status == 1 if hasattr(info, 'auto_renew_status') else info.auto_renewing if hasattr(info, 'auto_renewing') else False
            )

            return VerifyReceiptResponse(
                status="success",
                add_on_type=add_on_type,
                expires_at=expires_at,
                transaction_id=info.transaction_id if hasattr(info, 'transaction_id') else info.purchase_token,
                original_transaction_id=info.original_transaction_id if hasattr(info, 'original_transaction_id') else None
            )

        except Exception as e:
            return VerifyReceiptResponse(
                status="failed",
                error_message=f"Database error: {str(e)}"
            )

    def _get_add_on_type(self, product_id: str) -> Optional[str]:
        """Map product ID to add-on type."""
        if 'sync' in product_id.lower():
            return AddOnType.SYNC.value
        elif 'ai' in product_id.lower():
            return AddOnType.AI.value
        elif 'support' in product_id.lower():
            return AddOnType.SUPPORTER.value
        return None
```

**Testing**: Create `app/payments/test_service.py`

---

### 1.5 Create Payment Routes

**File**: `app/payments/routes.py`

```python
from fastapi import APIRouter, Depends, HTTPException
from typing import Tuple
from app.payments.models import (
    VerifyReceiptRequest,
    VerifyReceiptResponse,
    AppleWebhookNotification,
    GoogleWebhookNotification
)
from app.payments.service import PaymentService
from app.payments.dependencies import get_payment_service
from app.auth.dependencies import get_current_user
import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/payments", tags=["payments"])

@router.post("/verify", response_model=VerifyReceiptResponse)
async def verify_receipt(
    request: VerifyReceiptRequest,
    current_user: Tuple[str, str] = Depends(get_current_user),
    payment_service: PaymentService = Depends(get_payment_service)
):
    """
    Verify an App Store or Google Play receipt and grant entitlement.

    - Verifies receipt with Apple/Google
    - Stores receipt in database
    - Creates/updates user add-on entitlement
    """
    user_id, device_id = current_user

    logger.info("verify_receipt", user_id=user_id, platform=request.platform, product_id=request.product_id)

    result = await payment_service.verify_and_store_receipt(user_id, request)

    if result.status == "failed":
        logger.warning("receipt_verification_failed", user_id=user_id, error=result.error_message)
        raise HTTPException(status_code=400, detail=result.error_message)

    logger.info("receipt_verified", user_id=user_id, add_on_type=result.add_on_type)
    return result

@router.post("/webhook/apple")
async def apple_webhook(
    notification: AppleWebhookNotification,
    payment_service: PaymentService = Depends(get_payment_service)
):
    """
    Handle App Store Server Notifications.

    Notifications include:
    - INITIAL_BUY
    - DID_RENEW
    - DID_FAIL_TO_RENEW
    - DID_CHANGE_RENEWAL_STATUS
    - CANCEL
    """
    logger.info("apple_webhook", notification_type=notification.notification_type)

    # TODO: Implement webhook handling
    # - Verify notification signature
    # - Update user_add_ons based on notification type
    # - Handle renewals, cancellations, etc.

    return {"status": "ok"}

@router.post("/webhook/google")
async def google_webhook(
    notification: GoogleWebhookNotification,
    payment_service: PaymentService = Depends(get_payment_service)
):
    """
    Handle Google Play Developer Notifications via Cloud Pub/Sub.

    Notifications include:
    - SUBSCRIPTION_RENEWED
    - SUBSCRIPTION_CANCELED
    - SUBSCRIPTION_EXPIRED
    - etc.
    """
    logger.info("google_webhook", notification=notification.dict())

    # TODO: Implement webhook handling
    # - Verify message from Google Cloud Pub/Sub
    # - Update user_add_ons based on notification

    return {"status": "ok"}
```

**File**: `app/payments/dependencies.py`

```python
from app.payments.service import PaymentService
from app.payments.verifiers.apple_verifier import AppleReceiptVerifier
from app.payments.verifiers.google_verifier import GoogleReceiptVerifier
from app.master_db import get_master_db
from app.config import get_settings

settings = get_settings()

def get_payment_service() -> PaymentService:
    """Dependency for PaymentService."""
    apple_verifier = AppleReceiptVerifier(settings.apple_shared_secret)
    google_verifier = GoogleReceiptVerifier(settings.google_service_account_json)
    master_db = get_master_db()

    return PaymentService(
        master_db=master_db,
        apple_verifier=apple_verifier,
        google_verifier=google_verifier
    )
```

---

### 1.6 Update Master DB Methods

**File**: `app/master_db.py` (add new methods)

```python
# Add to MasterDatabaseManager class

def store_receipt(
    self,
    user_id: str,
    platform: str,
    receipt_data: str,
    product_id: str,
    transaction_id: str,
    verified_at: int
):
    """Store verified receipt."""
    receipt_id = str(uuid4())
    self.db.execute("""
        INSERT INTO receipts (id, user_id, platform, receipt_data, product_id, transaction_id, verified_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, [receipt_id, user_id, platform, receipt_data, product_id, transaction_id, verified_at])
    self.commit_and_sync()

def upsert_user_add_on(
    self,
    user_id: str,
    add_on_type: str,
    status: str,
    platform: str,
    product_id: str,
    transaction_id: str,
    original_transaction_id: Optional[str],
    purchase_date: int,
    expires_at: Optional[int],
    auto_renew: bool
):
    """Create or update user add-on entitlement."""
    self.db.execute("""
        INSERT INTO user_add_ons (
            user_id, add_on_type, status, platform, product_id,
            transaction_id, original_transaction_id, purchase_date,
            expires_at, auto_renew, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, add_on_type) DO UPDATE SET
            status = excluded.status,
            platform = excluded.platform,
            product_id = excluded.product_id,
            transaction_id = excluded.transaction_id,
            expires_at = excluded.expires_at,
            auto_renew = excluded.auto_renew,
            updated_at = excluded.updated_at
    """, [
        user_id, add_on_type, status, platform, product_id,
        transaction_id, original_transaction_id, purchase_date,
        expires_at, auto_renew, int(time.time()), int(time.time())
    ])
    self.commit_and_sync()
```

---

### 1.7 Register Payment Routes

**File**: `app/main.py` (modify)

```python
# Add import
from app.payments import routes as payment_routes

# Add router
app.include_router(payment_routes.router)
```

---

### 1.8 Update Configuration

**File**: `app/config.py` (add fields)

```python
# Add to Settings class
apple_shared_secret: str = ""
google_service_account_json: str = ""
```

**File**: `.env.example` (add)

```bash
APPLE_SHARED_SECRET=your_apple_shared_secret
GOOGLE_SERVICE_ACCOUNT_JSON={"type":"service_account",...}
```

---

### Phase 1 Testing

1. **Unit Tests**:
```bash
pytest app/payments/test_models.py
pytest app/payments/verifiers/test_apple_verifier.py
pytest app/payments/verifiers/test_google_verifier.py
pytest app/payments/test_service.py
```

2. **Integration Test**:
```python
# app/payments/test_integration.py
async def test_verify_ios_receipt():
    # Use Apple sandbox receipt
    response = await client.post(
        "/payments/verify",
        headers={"Authorization": f"Bearer {test_token}"},
        json={
            "platform": "ios",
            "receipt_data": "base64_sandbox_receipt",
            "product_id": "echolia.sync.monthly"
        }
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["add_on_type"] == "sync"
```

3. **Manual Test**:
- Set up Apple sandbox tester account
- Set up Google Play test track
- Purchase sync add-on in sandbox
- Verify receipt via `/payments/verify`
- Check `user_add_ons` table

---

## Phase 2: Core Sync (Week 3-4)

### Goal
Implement sync endpoints with E2EE support and entitlement checks.

### 2.1 Create Sync Models

**File**: `app/sync/models.py`

```python
from pydantic import BaseModel, Field
from typing import List, Optional, Dict

class SyncEntry(BaseModel):
    """
    Encrypted entry for sync.
    Backend never sees plaintext content.
    """
    id: str = Field(..., description="Entry UUID")
    device_id: str = Field(..., description="Source device UUID")
    encrypted_data: str = Field(..., description="Base64 encrypted payload")
    vector_clock: Dict[str, int] = Field(default_factory=dict, description="Device counters")
    version: int = Field(default=1, description="Entry version")
    is_deleted: bool = Field(default=False)
    created_at: int = Field(..., description="Unix timestamp")
    updated_at: int = Field(..., description="Unix timestamp")

class PullRequest(BaseModel):
    device_id: str
    last_sync_at: Optional[int] = Field(None, description="Unix timestamp of last pull, null for initial sync")
    vector_clock: Dict[str, int] = Field(default_factory=dict)

class PullResponse(BaseModel):
    entries: List[SyncEntry]
    deleted_ids: List[str]
    server_timestamp: int
    has_more: bool = False

class PushRequest(BaseModel):
    device_id: str
    entries: List[SyncEntry] = Field(default_factory=list)
    deleted_ids: List[str] = Field(default_factory=list)

class PushResponse(BaseModel):
    accepted: List[str] = Field(default_factory=list, description="Entry IDs accepted")
    conflicts: List[str] = Field(default_factory=list, description="Entry IDs with conflicts")
    rejected: List[str] = Field(default_factory=list, description="Entry IDs rejected")
    server_timestamp: int

class SyncStatusResponse(BaseModel):
    last_sync_at: Optional[int]
    entry_count: int
    pending_pushes: int = 0
    devices: List[dict]
```

---

### 2.2 Implement Sync Service

**File**: `app/sync/service.py`

```python
from app.sync.models import (
    PullRequest, PullResponse, PushRequest, PushResponse,
    SyncEntry, SyncStatusResponse
)
from app.database import TursoDatabaseManager
from app.master_db import MasterDatabaseManager
from typing import Dict
import time
import json

class SyncService:
    def __init__(
        self,
        user_db: TursoDatabaseManager,
        master_db: MasterDatabaseManager
    ):
        self.user_db = user_db
        self.master_db = master_db

    async def pull(self, user_id: str, request: PullRequest) -> PullResponse:
        """
        Pull changes since last_sync_at.
        Returns entries modified after last_sync_at.
        """
        if request.last_sync_at is None:
            # Initial sync - return all non-deleted entries
            rows = self.user_db.query("""
                SELECT
                    id, device_id, encrypted_data, vector_clock, version,
                    is_deleted, created_at, updated_at
                FROM synced_entries
                WHERE is_deleted = 0
                ORDER BY updated_at ASC
                LIMIT 1000
            """, [])
        else:
            # Delta sync - return entries updated since last sync
            rows = self.user_db.query("""
                SELECT
                    id, device_id, encrypted_data, vector_clock, version,
                    is_deleted, created_at, updated_at
                FROM synced_entries
                WHERE updated_at > ?
                ORDER BY updated_at ASC
                LIMIT 1000
            """, [request.last_sync_at])

        entries = []
        deleted_ids = []

        for row in rows:
            if row['is_deleted']:
                deleted_ids.append(row['id'])
            else:
                entries.append(SyncEntry(
                    id=row['id'],
                    device_id=row['device_id'],
                    encrypted_data=row['encrypted_data'],
                    vector_clock=json.loads(row['vector_clock']) if row['vector_clock'] else {},
                    version=row['version'],
                    is_deleted=bool(row['is_deleted']),
                    created_at=row['created_at'],
                    updated_at=row['updated_at']
                ))

        # Check if there are more entries
        has_more = len(rows) == 1000

        return PullResponse(
            entries=entries,
            deleted_ids=deleted_ids,
            server_timestamp=int(time.time()),
            has_more=has_more
        )

    async def push(self, user_id: str, request: PushRequest) -> PushResponse:
        """
        Push local changes to server.
        Handles conflict detection using vector clocks.
        """
        accepted = []
        conflicts = []
        rejected = []

        for entry in request.entries:
            try:
                # Check if entry exists
                existing = self.user_db.query("""
                    SELECT id, vector_clock, version, updated_at
                    FROM synced_entries
                    WHERE id = ?
                """, [entry.id])

                if existing:
                    # Entry exists - check for conflicts
                    existing_vc = json.loads(existing[0]['vector_clock']) if existing[0]['vector_clock'] else {}

                    if self._has_conflict(existing_vc, entry.vector_clock):
                        # Conflict detected - use Last-Write-Wins
                        if entry.updated_at > existing[0]['updated_at']:
                            # New entry is newer - accept
                            self._update_entry(entry)
                            accepted.append(entry.id)
                        else:
                            # Existing entry is newer - reject
                            conflicts.append(entry.id)
                    else:
                        # No conflict - update
                        self._update_entry(entry)
                        accepted.append(entry.id)
                else:
                    # New entry - insert
                    self._insert_entry(entry)
                    accepted.append(entry.id)

            except Exception as e:
                # Log error and reject entry
                print(f"Error processing entry {entry.id}: {e}")
                rejected.append(entry.id)

        # Handle deletions
        for entry_id in request.deleted_ids:
            try:
                self.user_db.execute("""
                    UPDATE synced_entries
                    SET is_deleted = 1, updated_at = ?
                    WHERE id = ?
                """, [int(time.time()), entry_id])
                accepted.append(entry_id)
            except Exception as e:
                print(f"Error deleting entry {entry_id}: {e}")
                rejected.append(entry_id)

        # Commit changes
        self.user_db.commit_and_sync()

        return PushResponse(
            accepted=accepted,
            conflicts=conflicts,
            rejected=rejected,
            server_timestamp=int(time.time())
        )

    def _has_conflict(self, vc1: Dict[str, int], vc2: Dict[str, int]) -> bool:
        """
        Check if two vector clocks conflict.
        Conflict occurs when neither clock dominates the other.
        """
        all_devices = set(vc1.keys()) | set(vc2.keys())

        vc1_greater = False
        vc2_greater = False

        for device_id in all_devices:
            v1 = vc1.get(device_id, 0)
            v2 = vc2.get(device_id, 0)

            if v1 > v2:
                vc1_greater = True
            elif v2 > v1:
                vc2_greater = True

        # Conflict if both clocks have some devices ahead
        return vc1_greater and vc2_greater

    def _insert_entry(self, entry: SyncEntry):
        """Insert new entry."""
        self.user_db.execute("""
            INSERT INTO synced_entries (
                id, device_id, encrypted_data, vector_clock, version,
                is_deleted, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            entry.id,
            entry.device_id,
            entry.encrypted_data,
            json.dumps(entry.vector_clock),
            entry.version,
            1 if entry.is_deleted else 0,
            entry.created_at,
            entry.updated_at
        ])

    def _update_entry(self, entry: SyncEntry):
        """Update existing entry."""
        self.user_db.execute("""
            UPDATE synced_entries
            SET
                device_id = ?,
                encrypted_data = ?,
                vector_clock = ?,
                version = ?,
                is_deleted = ?,
                updated_at = ?
            WHERE id = ?
        """, [
            entry.device_id,
            entry.encrypted_data,
            json.dumps(entry.vector_clock),
            entry.version,
            1 if entry.is_deleted else 0,
            entry.updated_at,
            entry.id
        ])

    async def get_status(self, user_id: str, device_id: str) -> SyncStatusResponse:
        """Get sync status for user."""
        # Get entry count
        count_result = self.user_db.query("""
            SELECT COUNT(*) as count
            FROM synced_entries
            WHERE is_deleted = 0
        """, [])
        entry_count = count_result[0]['count'] if count_result else 0

        # Get last sync time for this device
        last_sync = self.user_db.query("""
            SELECT MAX(updated_at) as last_sync
            FROM synced_entries
            WHERE device_id = ?
        """, [device_id])
        last_sync_at = last_sync[0]['last_sync'] if last_sync and last_sync[0]['last_sync'] else None

        # Get all user devices
        devices = self.master_db.get_user_devices(user_id)

        return SyncStatusResponse(
            last_sync_at=last_sync_at,
            entry_count=entry_count,
            pending_pushes=0,  # Client tracks this
            devices=[{
                "device_id": d['device_id'],
                "device_name": d['device_name'],
                "platform": d['platform'],
                "last_seen_at": d['last_seen_at']
            } for d in devices]
        )
```

---

### 2.3 Create Sync Dependencies (Entitlement Check)

**File**: `app/sync/dependencies.py`

```python
from fastapi import Depends, HTTPException
from typing import Tuple
from app.auth.dependencies import get_current_user
from app.master_db import get_master_db, MasterDatabaseManager
from app.add_ons.models import AddOnType

async def require_sync_add_on(
    current_user: Tuple[str, str] = Depends(get_current_user),
    master_db: MasterDatabaseManager = Depends(get_master_db)
) -> Tuple[str, str]:
    """
    Dependency that requires active sync add-on.
    Returns (user_id, device_id) if user has sync enabled.
    Raises 402 Payment Required if not subscribed.
    """
    user_id, device_id = current_user

    # Check if user has active sync add-on
    has_sync = master_db.is_add_on_active(user_id, AddOnType.SYNC)

    if not has_sync:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "sync_add_on_required",
                "message": "Sync add-on subscription required. Purchase in mobile app.",
                "product_id": "echolia.sync.monthly"
            }
        )

    return user_id, device_id
```

---

### 2.4 Create Sync Routes

**File**: `app/sync/routes.py`

```python
from fastapi import APIRouter, Depends
from typing import Tuple
from app.sync.models import (
    PullRequest, PullResponse,
    PushRequest, PushResponse,
    SyncStatusResponse
)
from app.sync.service import SyncService
from app.sync.dependencies import require_sync_add_on
from app.database import get_user_db
from app.master_db import get_master_db
import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/sync", tags=["sync"])

def get_sync_service(
    user_id: str,
    user_db = Depends(get_user_db),
    master_db = Depends(get_master_db)
) -> SyncService:
    """Dependency for SyncService."""
    return SyncService(user_db=user_db, master_db=master_db)

@router.post("/pull", response_model=PullResponse)
async def pull_changes(
    request: PullRequest,
    current_user: Tuple[str, str] = Depends(require_sync_add_on),
    sync_service: SyncService = Depends(get_sync_service)
):
    """
    Pull changes from server since last sync.

    - Returns encrypted entries modified since last_sync_at
    - Returns deleted entry IDs
    - Requires active sync add-on subscription
    """
    user_id, device_id = current_user

    logger.info("sync_pull", user_id=user_id, device_id=device_id, last_sync_at=request.last_sync_at)

    response = await sync_service.pull(user_id, request)

    logger.info("sync_pull_complete", user_id=user_id, entry_count=len(response.entries))

    return response

@router.post("/push", response_model=PushResponse)
async def push_changes(
    request: PushRequest,
    current_user: Tuple[str, str] = Depends(require_sync_add_on),
    sync_service: SyncService = Depends(get_sync_service)
):
    """
    Push local changes to server.

    - Uploads encrypted entries
    - Handles conflict detection with vector clocks
    - Requires active sync add-on subscription
    """
    user_id, device_id = current_user

    logger.info("sync_push", user_id=user_id, device_id=device_id, entry_count=len(request.entries))

    response = await sync_service.push(user_id, request)

    logger.info("sync_push_complete", user_id=user_id, accepted=len(response.accepted), conflicts=len(response.conflicts))

    return response

@router.get("/status", response_model=SyncStatusResponse)
async def get_sync_status(
    current_user: Tuple[str, str] = Depends(require_sync_add_on),
    sync_service: SyncService = Depends(get_sync_service)
):
    """
    Get current sync status.

    - Returns last sync time
    - Returns total entry count
    - Returns list of user's devices
    - Requires active sync add-on subscription
    """
    user_id, device_id = current_user

    response = await sync_service.get_status(user_id, device_id)

    return response
```

---

### 2.5 Register Sync Routes

**File**: `app/main.py`

```python
# Add import
from app.sync import routes as sync_routes

# Add router
app.include_router(sync_routes.router)
```

---

### Phase 2 Testing

1. **Unit Tests**:
```bash
pytest app/sync/test_service.py
pytest app/sync/test_dependencies.py
```

2. **Integration Tests**:
```python
# app/sync/test_integration.py

async def test_sync_without_subscription():
    """Test that sync requires subscription."""
    response = await client.post(
        "/sync/pull",
        headers={"Authorization": f"Bearer {test_token_without_sync}"},
        json={"device_id": "test-device", "last_sync_at": None}
    )
    assert response.status_code == 402
    assert "sync_add_on_required" in response.json()["detail"]["error"]

async def test_initial_sync():
    """Test initial sync (pull with last_sync_at=null)."""
    response = await client.post(
        "/sync/pull",
        headers={"Authorization": f"Bearer {test_token_with_sync}"},
        json={"device_id": "device-a", "last_sync_at": None, "vector_clock": {}}
    )
    assert response.status_code == 200
    data = response.json()
    assert "entries" in data
    assert "server_timestamp" in data

async def test_push_and_pull():
    """Test push entry then pull from another device."""
    # Device A pushes entry
    push_response = await client.post(
        "/sync/push",
        headers={"Authorization": f"Bearer {token_device_a}"},
        json={
            "device_id": "device-a",
            "entries": [{
                "id": "entry-123",
                "device_id": "device-a",
                "encrypted_data": "base64_encrypted_content",
                "vector_clock": {"device-a": 1},
                "version": 1,
                "is_deleted": False,
                "created_at": 1702300000,
                "updated_at": 1702300000
            }]
        }
    )
    assert push_response.status_code == 200
    assert "entry-123" in push_response.json()["accepted"]

    # Device B pulls entry
    pull_response = await client.post(
        "/sync/pull",
        headers={"Authorization": f"Bearer {token_device_b}"},
        json={"device_id": "device-b", "last_sync_at": None, "vector_clock": {}}
    )
    assert pull_response.status_code == 200
    entries = pull_response.json()["entries"]
    assert any(e["id"] == "entry-123" for e in entries)

async def test_conflict_resolution():
    """Test Last-Write-Wins conflict resolution."""
    # Both devices modify same entry offline
    # Device A updates (older timestamp)
    await client.post("/sync/push", json={
        "device_id": "device-a",
        "entries": [{
            "id": "entry-conflict",
            "device_id": "device-a",
            "encrypted_data": "version_a",
            "vector_clock": {"device-a": 5},
            "updated_at": 1702300000
        }]
    })

    # Device B updates (newer timestamp)
    await client.post("/sync/push", json={
        "device_id": "device-b",
        "entries": [{
            "id": "entry-conflict",
            "device_id": "device-b",
            "encrypted_data": "version_b",
            "vector_clock": {"device-b": 3},
            "updated_at": 1702300100  # 100 seconds later
        }]
    })

    # Pull should return Device B's version (newer)
    response = await client.post("/sync/pull", json={
        "device_id": "device-c",
        "last_sync_at": None
    })
    entries = response.json()["entries"]
    conflict_entry = next(e for e in entries if e["id"] == "entry-conflict")
    assert conflict_entry["encrypted_data"] == "version_b"
```

3. **Manual Test**:
- Create test user with sync add-on
- Use Bruno/Postman to test endpoints
- Verify encrypted_data is never decrypted by backend
- Test with multiple devices

---

## Phase 3: No Backend Changes

Phase 3 (Offline Queue) is handled entirely on mobile/desktop. No backend changes needed.

---

## Phase 4: Desktop Inference Relay (Week 6-7)

### Goal
Enable mobile to use desktop AI via backend relay.

### 4.1 Add Per-User DB Migration

**File**: `app/database.py` (add v002 migration)

```python
def _migration_v002_relay_tables(self):
    """Add device capabilities and inference relay tables."""
    self.db.executescript("""
        CREATE TABLE IF NOT EXISTS device_capabilities (
            device_id TEXT PRIMARY KEY,
            can_inference INTEGER DEFAULT 0,
            inference_models TEXT,  -- JSON array
            last_heartbeat_at INTEGER NOT NULL,
            is_online INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS inference_relay_queue (
            id TEXT PRIMARY KEY,
            source_device_id TEXT NOT NULL,
            target_device_id TEXT NOT NULL,
            encrypted_payload TEXT NOT NULL,
            encrypted_result TEXT,
            status TEXT NOT NULL,  -- 'pending', 'processing', 'completed', 'failed'
            created_at INTEGER NOT NULL,
            completed_at INTEGER,
            error_message TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_relay_target
        ON inference_relay_queue(target_device_id, status);

        CREATE INDEX IF NOT EXISTS idx_relay_source
        ON inference_relay_queue(source_device_id, status);
    """)
    self.db.execute("UPDATE schema_version SET version = 2, applied_at = ?", [int(time.time())])
```

---

### 4.2 Create Device Routes

**File**: `app/devices/routes.py`

```python
from fastapi import APIRouter, Depends
from typing import Tuple, List
from pydantic import BaseModel
from app.auth.dependencies import get_current_user
from app.database import get_user_db
import structlog
import time
import json

logger = structlog.get_logger()
router = APIRouter(prefix="/devices", tags=["devices"])

class UpdateCapabilitiesRequest(BaseModel):
    device_id: str
    can_inference: bool
    inference_models: List[str]

class HeartbeatRequest(BaseModel):
    device_id: str

class CapableDevice(BaseModel):
    device_id: str
    device_name: str
    platform: str
    is_online: bool
    inference_models: List[str]
    last_seen: int

class CapableDevicesResponse(BaseModel):
    devices: List[CapableDevice]

@router.post("/capabilities")
async def update_capabilities(
    request: UpdateCapabilitiesRequest,
    current_user: Tuple[str, str] = Depends(get_current_user),
    user_db = Depends(get_user_db)
):
    """
    Update device capabilities (desktop only).
    Desktop registers its inference capabilities on startup.
    """
    user_id, device_id = current_user

    # Verify device_id matches token
    if request.device_id != device_id:
        raise HTTPException(403, "Device ID mismatch")

    logger.info("update_capabilities", user_id=user_id, device_id=device_id, can_inference=request.can_inference)

    now = int(time.time())
    user_db.execute("""
        INSERT INTO device_capabilities (
            device_id, can_inference, inference_models, last_heartbeat_at, is_online
        ) VALUES (?, ?, ?, ?, 1)
        ON CONFLICT(device_id) DO UPDATE SET
            can_inference = excluded.can_inference,
            inference_models = excluded.inference_models,
            last_heartbeat_at = excluded.last_heartbeat_at,
            is_online = 1
    """, [device_id, 1 if request.can_inference else 0, json.dumps(request.inference_models), now])

    user_db.commit_and_sync()

    return {"status": "ok"}

@router.post("/heartbeat")
async def heartbeat(
    request: HeartbeatRequest,
    current_user: Tuple[str, str] = Depends(get_current_user),
    user_db = Depends(get_user_db)
):
    """
    Update device online status (desktop only).
    Desktop sends heartbeat every 30s.
    """
    user_id, device_id = current_user

    if request.device_id != device_id:
        raise HTTPException(403, "Device ID mismatch")

    now = int(time.time())
    user_db.execute("""
        UPDATE device_capabilities
        SET last_heartbeat_at = ?, is_online = 1
        WHERE device_id = ?
    """, [now, device_id])

    # Mark as offline if heartbeat is > 60s old
    user_db.execute("""
        UPDATE device_capabilities
        SET is_online = 0
        WHERE last_heartbeat_at < ? - 60
    """, [now])

    user_db.commit_and_sync()

    return {"status": "ok"}

@router.get("/capable", response_model=CapableDevicesResponse)
async def get_capable_devices(
    current_user: Tuple[str, str] = Depends(get_current_user),
    user_db = Depends(get_user_db),
    master_db = Depends(get_master_db)
):
    """
    Get user's devices capable of inference.
    Mobile queries this to discover available desktop devices.
    """
    user_id, device_id = current_user

    # Get devices with inference capability
    rows = user_db.query("""
        SELECT device_id, can_inference, inference_models, last_heartbeat_at, is_online
        FROM device_capabilities
        WHERE can_inference = 1
    """, [])

    devices = []
    for row in rows:
        # Get device info from master DB
        device_info = master_db.get_device_info(row['device_id'])
        if device_info:
            devices.append(CapableDevice(
                device_id=row['device_id'],
                device_name=device_info['device_name'],
                platform=device_info['platform'],
                is_online=bool(row['is_online']),
                inference_models=json.loads(row['inference_models']) if row['inference_models'] else [],
                last_seen=row['last_heartbeat_at']
            ))

    return CapableDevicesResponse(devices=devices)
```

---

### 4.3 Create Inference Relay Routes

**File**: `app/inference/relay_routes.py`

```python
from fastapi import APIRouter, Depends, HTTPException
from typing import Tuple, List, Optional
from pydantic import BaseModel
from app.auth.dependencies import get_current_user
from app.database import get_user_db
from uuid import uuid4
import structlog
import time

logger = structlog.get_logger()
router = APIRouter(prefix="/inference", tags=["inference-relay"])

class RelayInferenceRequest(BaseModel):
    target_device_id: str
    task: str  # "memory_distillation", "tagging", etc.
    encrypted_payload: str
    nonce: str
    mac: str

class RelayInferenceResponse(BaseModel):
    relay_id: str
    status: str

class RelayRequest(BaseModel):
    relay_id: str
    source_device_id: str
    task: str
    encrypted_payload: str
    created_at: int

class RespondRelayRequest(BaseModel):
    relay_id: str
    encrypted_result: str
    nonce: str
    mac: str

class RelayStatusResponse(BaseModel):
    relay_id: str
    status: str
    encrypted_result: Optional[str] = None
    completed_at: Optional[int] = None
    error_message: Optional[str] = None

@router.post("/relay", response_model=RelayInferenceResponse)
async def relay_inference(
    request: RelayInferenceRequest,
    current_user: Tuple[str, str] = Depends(get_current_user),
    user_db = Depends(get_user_db),
    master_db = Depends(get_master_db)
):
    """
    Relay encrypted inference request to target device (desktop).
    Mobile calls this to request desktop inference.
    """
    user_id, source_device_id = current_user

    # Verify target device belongs to user
    device_info = master_db.get_device_info(request.target_device_id)
    if not device_info or device_info['user_id'] != user_id:
        raise HTTPException(403, "Target device not found")

    # Check if target device is online
    capability = user_db.query("""
        SELECT is_online FROM device_capabilities WHERE device_id = ?
    """, [request.target_device_id])

    if not capability or not capability[0]['is_online']:
        raise HTTPException(503, "Target device is offline")

    # Store relay request
    relay_id = str(uuid4())
    now = int(time.time())

    user_db.execute("""
        INSERT INTO inference_relay_queue (
            id, source_device_id, target_device_id, encrypted_payload,
            status, created_at
        ) VALUES (?, ?, ?, ?, 'pending', ?)
    """, [relay_id, source_device_id, request.target_device_id,
          json.dumps({
              "task": request.task,
              "encrypted_payload": request.encrypted_payload,
              "nonce": request.nonce,
              "mac": request.mac
          }), now])

    user_db.commit_and_sync()

    logger.info("relay_created", relay_id=relay_id, target=request.target_device_id)

    return RelayInferenceResponse(relay_id=relay_id, status="pending")

@router.get("/poll", response_model=List[RelayRequest])
async def poll_relay_requests(
    current_user: Tuple[str, str] = Depends(get_current_user),
    user_db = Depends(get_user_db)
):
    """
    Poll for pending relay requests (desktop only).
    Desktop calls this every 5s to check for work.
    """
    user_id, device_id = current_user

    rows = user_db.query("""
        SELECT id, source_device_id, encrypted_payload, created_at
        FROM inference_relay_queue
        WHERE target_device_id = ? AND status = 'pending'
        ORDER BY created_at ASC
        LIMIT 10
    """, [device_id])

    # Mark as processing
    for row in rows:
        user_db.execute("""
            UPDATE inference_relay_queue
            SET status = 'processing'
            WHERE id = ?
        """, [row['id']])

    user_db.commit_and_sync()

    requests = []
    for row in rows:
        payload = json.loads(row['encrypted_payload'])
        requests.append(RelayRequest(
            relay_id=row['id'],
            source_device_id=row['source_device_id'],
            task=payload['task'],
            encrypted_payload=payload['encrypted_payload'],
            created_at=row['created_at']
        ))

    return requests

@router.post("/respond")
async def respond_relay(
    request: RespondRelayRequest,
    current_user: Tuple[str, str] = Depends(get_current_user),
    user_db = Depends(get_user_db)
):
    """
    Submit relay inference result (desktop only).
    Desktop calls this after processing relay request.
    """
    user_id, device_id = current_user

    # Verify relay exists and is assigned to this device
    relay = user_db.query("""
        SELECT target_device_id, status
        FROM inference_relay_queue
        WHERE id = ?
    """, [request.relay_id])

    if not relay:
        raise HTTPException(404, "Relay not found")

    if relay[0]['target_device_id'] != device_id:
        raise HTTPException(403, "Not your relay")

    if relay[0]['status'] != 'processing':
        raise HTTPException(400, f"Relay status is {relay[0]['status']}, expected 'processing'")

    # Store result
    now = int(time.time())
    user_db.execute("""
        UPDATE inference_relay_queue
        SET
            encrypted_result = ?,
            status = 'completed',
            completed_at = ?
        WHERE id = ?
    """, [json.dumps({
        "encrypted_result": request.encrypted_result,
        "nonce": request.nonce,
        "mac": request.mac
    }), now, request.relay_id])

    user_db.commit_and_sync()

    logger.info("relay_completed", relay_id=request.relay_id)

    return {"status": "ok"}

@router.get("/status/{relay_id}", response_model=RelayStatusResponse)
async def get_relay_status(
    relay_id: str,
    current_user: Tuple[str, str] = Depends(get_current_user),
    user_db = Depends(get_user_db)
):
    """
    Check status of relay request (mobile only).
    Mobile polls this to get result.
    """
    user_id, device_id = current_user

    row = user_db.query("""
        SELECT status, encrypted_result, completed_at, error_message
        FROM inference_relay_queue
        WHERE id = ? AND source_device_id = ?
    """, [relay_id, device_id])

    if not row:
        raise HTTPException(404, "Relay not found")

    result = row[0]
    response = RelayStatusResponse(
        relay_id=relay_id,
        status=result['status'],
        completed_at=result['completed_at'],
        error_message=result['error_message']
    )

    if result['status'] == 'completed' and result['encrypted_result']:
        result_data = json.loads(result['encrypted_result'])
        response.encrypted_result = result_data['encrypted_result']

    return response
```

---

### 4.4 Register New Routes

**File**: `app/main.py`

```python
from app.devices import routes as device_routes
from app.inference import relay_routes

app.include_router(device_routes.router)
app.include_router(relay_routes.router)
```

---

### Phase 4 Testing

1. **Unit Tests**:
```bash
pytest app/devices/test_routes.py
pytest app/inference/test_relay_routes.py
```

2. **Integration Test**:
```python
async def test_relay_flow():
    # Desktop registers capability
    await client.post("/devices/capabilities", headers={"Authorization": desktop_token}, json={
        "device_id": "desktop-1",
        "can_inference": True,
        "inference_models": ["llama3-8b"]
    })

    # Desktop sends heartbeat
    await client.post("/devices/heartbeat", headers={"Authorization": desktop_token}, json={
        "device_id": "desktop-1"
    })

    # Mobile discovers capable devices
    response = await client.get("/devices/capable", headers={"Authorization": mobile_token})
    assert len(response.json()["devices"]) == 1

    # Mobile creates relay request
    relay_response = await client.post("/inference/relay", headers={"Authorization": mobile_token}, json={
        "target_device_id": "desktop-1",
        "task": "memory_distillation",
        "encrypted_payload": "encrypted_data",
        "nonce": "nonce",
        "mac": "mac"
    })
    relay_id = relay_response.json()["relay_id"]

    # Desktop polls for requests
    poll_response = await client.get("/inference/poll", headers={"Authorization": desktop_token})
    assert len(poll_response.json()) == 1
    assert poll_response.json()[0]["relay_id"] == relay_id

    # Desktop submits result
    await client.post("/inference/respond", headers={"Authorization": desktop_token}, json={
        "relay_id": relay_id,
        "encrypted_result": "result",
        "nonce": "nonce2",
        "mac": "mac2"
    })

    # Mobile checks status
    status_response = await client.get(f"/inference/status/{relay_id}", headers={"Authorization": mobile_token})
    assert status_response.json()["status"] == "completed"
    assert status_response.json()["encrypted_result"] == "result"
```

---

## Deployment Checklist

### Environment Variables
```bash
# .env
TURSO_ORG_URL=...
TURSO_AUTH_TOKEN=...
JWT_SECRET=...
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
APPLE_TEAM_ID=...
APPLE_KEY_ID=...
APPLE_PRIVATE_KEY=...
APPLE_SHARED_SECRET=...
GOOGLE_SERVICE_ACCOUNT_JSON=...
```

### Database Migrations
```bash
# Run migrations
python -m app.database migrate

# Verify schema version
python -m app.database version
```

### API Documentation
```bash
# Start server
uvicorn app.main:app --reload

# Visit http://localhost:8000/docs
```

### Testing
```bash
# All tests
pytest

# With coverage
pytest --cov=app --cov-report=html

# Specific module
pytest app/payments/
pytest app/sync/
pytest app/devices/
```

---

## Next Steps

1. ✅ Complete Phase 1 implementation
2. ✅ Complete Phase 2 implementation
3. ✅ Complete Phase 4 implementation (Phase 3 is client-side)
4. Deploy to staging environment
5. Test with mobile/desktop clients
6. Monitor logs and metrics
7. Deploy to production

---

**Document Version**: 1.0
**Last Updated**: 2025-12-12
**Status**: Ready for implementation



----
 Implemented

  - Sync core: Sync models/service/routes with entitlement checks, vector-clock LWW conflict handling, deletes, status
    endpoint; router registered.
  - Per-user DB access: get_user_db dependency; per-user migration v002 for device capabilities and inference relay
    tables.
  - Relay plumbing: Device capability/heartbeat/discovery endpoints; inference relay queue/poll/respond/status
    endpoints; routers registered.
  - Payments/webhooks: Receipt verification flow uses Apple/Google verifiers; receipts stored via master DB; add-on
    upsert/update helpers; Apple/Google webhook routes process events and update add-on status.

  Not done / gaps

  - Payment hardening: No Apple signature verification, no Google Pub/Sub verification; webhook event/status handling
    is minimal; no staging/production config validation.
  - Testing: No integration tests for sync, relay, or payments/webhooks; existing unit tests were not run.
  - Ops/migrations: v002 migration exists but no runner hook/instructions added; compatibility with existing replicas
    unverified.
  - Sync polish: No rate/size telemetry, no integration tests per plan.
  - Relay polish: No replay protection/nonce checks; only basic online/offline heuristics.

  If you want next steps, I can (1) add Apple signature and Google Pub/Sub verification for webhooks, (2) add
  migration runner guidance, and (3) create integration tests for sync/relay/payment flows.