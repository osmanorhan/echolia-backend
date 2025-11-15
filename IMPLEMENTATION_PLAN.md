# Echolia Backend Implementation Plan

**Updated**: 2025-11-15
**Status**: Phase 1 Starting
**Architecture**: Privacy-first, Add-ons based monetization

## Product Philosophy

Echolia is an indie, privacy-first personal AI companion following Obsidian's ethical monetization model:
- Base app works fully offline (no registration required)
- Optional add-ons for cloud features (Sync $2/mo, AI $3/mo)
- Mobile-only purchases (App Store/Play Store)
- Zero-knowledge encryption for all user data
- Protest against surveillance capitalism

## Architecture Overview

### Key Architectural Decisions

✅ **What We're Building**:
- OAuth-only authentication (Google + Apple Sign-In)
- Master database for users, devices, and add-ons
- Per-user databases for encrypted user data (unchanged)
- Add-on system (not subscription tiers)
- Receipt verification for mobile purchases
- Zero-knowledge LLM proxy (AI Add-on)
- Feature flags based on active add-ons

❌ **What We're Removing**:
- ~~Anonymous registration~~
- ~~Username/password authentication~~
- ~~RSA device pairing~~
- ~~Complex device attestation~~

### Database Architecture

**Master Database** (`echolia_master.db`):
- Users (OAuth identities)
- Devices (per user)
- Add-ons (subscriptions)
- Receipts (purchase verification)
- AI usage quota (anti-abuse)

**Per-User Databases** (`user_{uuid}.db`):
- Encrypted entries, memories, tags (unchanged)
- Embeddings (unchanged)
- LLM usage tracking (unchanged)

## Implementation Phases

### Phase 1: OAuth Authentication & Master Database (START HERE)

**Goal**: Replace anonymous auth with OAuth, create master database for users

**Tasks**:
1. Create master database manager
2. Implement OAuth token verification (Google + Apple)
3. Update auth service for OAuth flow
4. Migrate auth routes to OAuth endpoints
5. Update JWT generation to include user_id from OAuth
6. Add device registration during sign-in
7. Remove old anonymous auth code

**New Files**:
```
app/
├── master_db.py                 # Master database manager
└── auth/
    ├── oauth_verifiers.py       # Google + Apple token verification
    └── models.py                # Updated for OAuth models
```

**Modified Files**:
```
app/auth/service.py              # OAuth sign-in flow
app/auth/routes.py               # OAuth endpoints
app/config.py                    # OAuth credentials
requirements.txt                 # OAuth libraries
```

**API Endpoints**:
```
POST   /auth/oauth/signin        # Sign in with Google/Apple
POST   /auth/refresh             # Refresh tokens (unchanged)
GET    /auth/devices             # List user's devices
DELETE /auth/device/{device_id}  # Remove device
GET    /auth/me                  # Get current user info
```

**Master Database Schema**:
```sql
-- users table
CREATE TABLE users (
    user_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    provider_user_id TEXT NOT NULL,
    email TEXT,
    name TEXT,
    created_at INTEGER NOT NULL,
    UNIQUE(provider, provider_user_id)
);

-- user_devices table
CREATE TABLE user_devices (
    device_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    device_name TEXT NOT NULL,
    platform TEXT NOT NULL,
    app_version TEXT,
    last_seen_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
```

**Dependencies to Add**:
```
google-auth>=2.27.0
google-auth-oauthlib>=1.2.0
PyJWT>=2.8.0
cryptography>=41.0.0
python-jose[cryptography]>=3.3.0
```

**Success Criteria**:
- ✅ User can sign in with Google OAuth
- ✅ User can sign in with Apple Sign-In
- ✅ Device registered in master database
- ✅ JWT tokens generated with user_id
- ✅ Per-user database created on first sign-in
- ✅ Old anonymous auth removed

---

### Phase 2: Add-Ons Management System

**Goal**: Implement add-on tracking and feature flags

**Tasks**:
1. Add add-ons schema to master database
2. Create add-ons service
3. Implement feature flag system
4. Add add-ons routes
5. Create dependency for add-on checks

**New Files**:
```
app/add_ons/
├── __init__.py
├── models.py                    # AddOnType, UserAddOns
├── service.py                   # Add-on management
└── routes.py                    # Add-on endpoints
```

**Master Database Schema Addition**:
```sql
-- user_add_ons table
CREATE TABLE user_add_ons (
    user_id TEXT NOT NULL,
    add_on_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    platform TEXT NOT NULL,
    product_id TEXT NOT NULL,
    transaction_id TEXT NOT NULL,
    original_transaction_id TEXT,
    purchase_date INTEGER NOT NULL,
    expires_at INTEGER,
    auto_renew BOOLEAN DEFAULT false,
    cancelled_at INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, add_on_type),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
```

**API Endpoints**:
```
GET /add-ons/status              # Get user's add-ons
GET /add-ons/features            # Get feature flags
```

**Success Criteria**:
- ✅ Add-ons stored in master database
- ✅ Feature flags returned based on active add-ons
- ✅ Dependencies for add-on checks work

---

### Phase 3: Payment Verification

**Goal**: Verify App Store and Play Store receipts

**Tasks**:
1. Implement Apple receipt verifier
2. Implement Google receipt verifier
3. Create payment service
4. Add payment routes
5. Implement webhook handlers for renewals
6. Add receipts table to master database

**New Files**:
```
app/payments/
├── __init__.py
├── models.py                    # Receipt models
├── service.py                   # Payment verification
├── routes.py                    # Payment endpoints
├── verifiers/
│   ├── __init__.py
│   ├── apple_verifier.py        # App Store verification
│   └── google_verifier.py       # Play Store verification
└── webhooks/
    ├── __init__.py
    ├── apple_webhook_handler.py
    └── google_webhook_handler.py
```

**Master Database Schema Addition**:
```sql
-- receipts table
CREATE TABLE receipts (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    receipt_data TEXT NOT NULL,
    product_id TEXT NOT NULL,
    transaction_id TEXT NOT NULL,
    verified_at INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
```

**API Endpoints**:
```
POST /payments/verify            # Verify receipt
POST /payments/webhook/apple     # Apple webhooks
POST /payments/webhook/google    # Google webhooks
```

**Dependencies to Add**:
```
requests>=2.31.0
```

**Configuration**:
```python
APPLE_SHARED_SECRET: str
GOOGLE_SERVICE_ACCOUNT_JSON: str
PRODUCT_IDS: dict
```

**Success Criteria**:
- ✅ Apple receipts verified
- ✅ Google receipts verified
- ✅ Add-ons activated after purchase
- ✅ Webhooks handle renewals/cancellations

---

### Phase 4: LLM Inference Service (AI Add-on)

**Goal**: Zero-knowledge LLM proxy with add-on requirement

**Tasks**:
1. Create LLM service with add-on checks
2. Implement zero-knowledge encryption/decryption
3. Add LLM provider integrations (Anthropic, OpenAI, Google)
4. Implement rate limiting (anti-abuse)
5. Add AI usage quota tracking
6. Create LLM routes

**New Files**:
```
app/llm/
├── __init__.py
├── models.py                    # Inference models
├── service.py                   # LLM orchestration
├── routes.py                    # LLM endpoints
├── crypto.py                    # Zero-knowledge crypto
└── providers/
    ├── __init__.py
    ├── anthropic.py             # Anthropic integration
    ├── openai.py                # OpenAI integration
    └── google.py                # Google AI integration
```

**Master Database Schema Addition**:
```sql
-- ai_usage_quota table (anti-abuse)
CREATE TABLE ai_usage_quota (
    user_id TEXT NOT NULL,
    date TEXT NOT NULL,
    request_count INTEGER DEFAULT 0,
    last_reset_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, date),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
```

**API Endpoints**:
```
POST /llm/generate               # Zero-knowledge inference
GET  /llm/models                 # Available models
GET  /llm/usage                  # Usage stats
```

**Dependencies to Add**:
```
anthropic>=0.18.0
openai>=1.12.0
google-generativeai>=0.3.0
redis>=5.0.0                     # Optional: distributed rate limiting
```

**Configuration**:
```python
ANTHROPIC_API_KEY: str
OPENAI_API_KEY: str
GOOGLE_AI_API_KEY: Optional[str]
AI_RATE_LIMIT_HOURLY: int = 500
AI_RATE_LIMIT_DAILY: int = 5000
```

**Zero-Knowledge Flow**:
```
Client:
1. Generate ephemeral AES key
2. Encrypt prompt with AES
3. Encrypt AES key with server's public RSA key
4. Send encrypted_prompt + encrypted_key

Server:
1. Check AI add-on active
2. Check rate limits
3. Decrypt AES key with server's private RSA key
4. Decrypt prompt with AES key (in-memory only)
5. Call LLM provider
6. Encrypt response with same AES key
7. Wipe everything from memory
8. Return encrypted response

Client:
1. Decrypt response with ephemeral AES key
```

**Success Criteria**:
- ✅ Only works with active AI add-on
- ✅ Zero-knowledge encryption working
- ✅ Anthropic provider working
- ✅ OpenAI provider working
- ✅ Rate limiting prevents abuse
- ✅ Usage tracked for transparency

---

### Phase 5: Sync Service (Sync Add-on)

**Goal**: Cross-device sync with add-on requirement

**Tasks**:
1. Create sync service with add-on checks
2. Implement delta sync with vector clocks
3. Add conflict resolution
4. Create sync routes
5. Test cross-device synchronization

**New Files**:
```
app/sync/
├── __init__.py
├── models.py                    # Sync models
├── service.py                   # Sync logic
└── routes.py                    # Sync endpoints
```

**API Endpoints**:
```
POST /sync/push                  # Push local changes
POST /sync/pull                  # Pull remote changes
GET  /sync/status                # Sync status
```

**Success Criteria**:
- ✅ Only works with active Sync add-on
- ✅ Delta sync working
- ✅ Conflict resolution working
- ✅ Cross-device sync tested

---

## Migration Strategy

### Step 1: Backup Current State
```bash
git checkout -b backup-anonymous-auth
git push -u origin backup-anonymous-auth
```

### Step 2: Create Master Database
- Add `app/master_db.py`
- Initialize master database schema
- Test connection

### Step 3: Implement OAuth Verification
- Add OAuth verifiers
- Test Google token verification
- Test Apple token verification

### Step 4: Update Auth Service
- Implement OAuth sign-in flow
- Update JWT generation
- Remove anonymous auth code

### Step 5: Test Migration
- Test Google sign-in flow end-to-end
- Test Apple sign-in flow end-to-end
- Test device registration
- Test per-user database creation

### Step 6: Clean Up
- Remove old auth code
- Update documentation
- Update tests

---

## Product IDs

### iOS (App Store)
```
echolia.sync.monthly            # $2/month
echolia.ai.monthly              # $3/month
echolia.support.small           # $5 one-time
echolia.support.medium          # $10 one-time
echolia.support.large           # $25 one-time
```

### Android (Play Store)
```
Same product IDs as iOS
```

---

## Rate Limits (Anti-Abuse, Not Paywalls)

AI Add-on users get unlimited use for $3/month, but with soft limits to prevent abuse:

- **500 requests/hour**: Normal users won't hit this
- **5,000 requests/day**: Excessive use protection
- **Philosophy**: Trust users, prevent bad actors

If exceeded: Friendly message, not hard block.

---

## Testing Strategy

### Phase 1 Testing
- [ ] Google OAuth token verification
- [ ] Apple OAuth token verification
- [ ] Device registration
- [ ] JWT generation with OAuth
- [ ] Per-user database creation on sign-in

### Phase 2 Testing
- [ ] Add-on activation
- [ ] Feature flag generation
- [ ] Add-on expiration checking

### Phase 3 Testing
- [ ] Apple receipt verification
- [ ] Google receipt verification
- [ ] Webhook handling
- [ ] Auto-renewal tracking

### Phase 4 Testing
- [ ] Zero-knowledge encryption/decryption
- [ ] Anthropic provider
- [ ] OpenAI provider
- [ ] Rate limiting
- [ ] Add-on requirement enforcement

### Phase 5 Testing
- [ ] Delta sync
- [ ] Conflict resolution
- [ ] Cross-device sync
- [ ] Add-on requirement enforcement

---

## Success Metrics

### Technical
- OAuth sign-in success rate > 99%
- Add-on verification latency < 100ms
- LLM inference latency < 2s (95th percentile)
- Sync conflict rate < 1%

### Business
- 0-100 users: ~$4/month infrastructure cost
- Average add-on attach rate: 30% (target)
- Churn rate: < 5%/month
- Support burden: < 1 hour/week

---

## Next Steps

1. **Start Phase 1**: OAuth authentication
2. Create master database
3. Implement Google OAuth verification
4. Implement Apple OAuth verification
5. Update auth service
6. Test end-to-end sign-in flow
7. Clean up old anonymous auth

**Current Branch**: `claude/update-plan-start-auth-019PHEuHXY5SMtNWRhnkyoiv`
