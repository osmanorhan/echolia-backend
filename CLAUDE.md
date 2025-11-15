# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Echolia Backend is a privacy-first sync and LLM inference service for the Echolia desktop and mobile apps. It uses **OAuth-based authentication** (Google + Apple Sign-In) with a **dual-database architecture**: a master database for users/subscriptions and per-user databases for encrypted data.

**Current Status**: Phase 1 complete (OAuth authentication, master database, add-ons infrastructure). Sync, LLM, payments, and embeddings services are planned but not yet implemented.

**Product Philosophy**: Indie, privacy-first AI companion following Obsidian's ethical monetization model. Base app works fully offline; optional add-ons (Sync $2/mo, AI $3/mo) enhance experience. No paywalls, no dark patterns.

## Development Commands

### Local Development (Recommended - using uv)
```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies (uv handles virtual environment automatically)
uv sync

# Run development server with auto-reload
uv run uvicorn app.main:app --reload

# Alternative: Run with Python module
uv run python -m app.main

# Access API at http://localhost:8000
# API docs (dev only) at http://localhost:8000/docs
```

### Testing
```bash
# Run all tests (with uv)
uv run pytest tests/

# Run specific test file
uv run pytest tests/test_auth.py -v

# Run with verbose output
uv run pytest -v

# Install dev dependencies
uv sync --extra dev
```

### Code Quality
```bash
# Format code
uv run black app/

# Lint code
uv run ruff check app/

# Type checking
uv run mypy app/
```

### Docker (Production-like)
```bash
# Build and start services
# Note: First build may take 5-10 minutes (libsql compiles from source)
docker-compose up -d

# View logs
docker-compose logs -f api

# Rebuild after code changes
docker-compose down
docker-compose build --no-cache
docker-compose up -d

# Access API at http://localhost:8000
```

**Note**: Docker uses system-wide package installation via `uv pip install --system`, so the container runs `uvicorn` directly (not `uv run uvicorn`). The `uv run` command is primarily for local development where uv manages virtual environments automatically.

### Database Management
```bash
# Master database (users, devices, add-ons)
turso db shell echolia_master

# List all user databases
turso db list | grep user_

# Access a specific user's database
turso db shell user_<uuid>

# Check schema version
turso db shell echolia_master "SELECT * FROM schema_version;"
```

## Architecture & Key Concepts

### Dual-Database Architecture

**Master Database** (`echolia_master.db`):
- OAuth identities (Google, Apple)
- Devices (per user, tracked in master DB)
- Add-ons/subscriptions (Sync, AI, Supporter)
- Receipts (purchase verification)
- AI usage quota (anti-abuse)

**Per-User Databases** (`user_{uuid}.db`):
- Encrypted entries, memories, tags
- Embeddings
- LLM usage tracking
- Perfect data isolation
- GDPR compliance: delete database = user gone

**Key files**:
- `app/master_db.py` - `MasterDatabaseManager` class handles master database operations
- `app/database.py` - `TursoDatabaseManager` class handles per-user database operations
- Master database connections are direct (no embedded replicas)
- Per-user database connections use embedded replicas with LRU cache (`@lru_cache(maxsize=100)`)

### OAuth-Based Authentication

**Sign-In Flow**:
1. User taps "Sign in with Google" or "Sign in with Apple" in mobile/desktop app
2. App performs OAuth with provider (native SDKs: GoogleSignIn, Sign in with Apple)
3. App receives `id_token` (JWT) from provider
4. App sends `id_token` + device info to `POST /auth/oauth/signin`
5. Server verifies `id_token` with provider's public keys
6. Server creates/retrieves user in master database
7. Server registers device in master database
8. Server creates per-user database if first sign-in
9. Server returns `access_token` + `refresh_token` + `add_ons` status

**Key Features**:
- No email/password registration
- No anonymous accounts
- Device-based authentication (each device has unique ID)
- JWT tokens with device fingerprinting
- Access tokens expire in 1 hour
- Refresh tokens expire in 30 days
- Device deletion immediately invalidates tokens
- Zero-knowledge: user data encrypted client-side

**Key files**:
- `app/auth/oauth_verifiers.py` - Google + Apple token verification
- `app/auth/service.py` - `AuthService` contains all auth business logic
- `app/auth/crypto.py` - JWT generation and verification
- `app/auth/models.py` - Pydantic models for OAuth requests/responses
- `app/auth/routes.py` - FastAPI endpoints
- `app/auth/dependencies.py` - JWT verification dependency for protected routes

### Add-Ons System

**Philosophy**: Users buy optional value, not access to basic features.

**Add-On Types**:
- **Sync Add-on** ($2/month): Cross-device sync, unlimited devices
- **AI Add-on** ($3/month): Server-side AI inference (zero-knowledge)
- **Support Echolia** ($5-$50 one-time): Thank you badge, support development

**Combined**: $5/month for both add-ons = full-featured Echolia.

**Implementation**:
- Add-ons stored in `user_add_ons` table in master database
- Status: `active`, `expired`, `cancelled`
- Expiration checked on each request
- Feature flags returned with `/auth/oauth/signin` and `/auth/me` responses

**Key files**:
- `app/master_db.py` - Add-on management methods
- `app/auth/models.py` - `UserAddOns` model
- Future: `app/add_ons/` module (Phase 2)

### Module Structure

The codebase follows a modular FastAPI structure:

```
app/
├── main.py              # FastAPI app, middleware, startup/shutdown
├── config.py            # Pydantic settings from environment variables
├── master_db.py         # MasterDatabaseManager (users, devices, add-ons)
├── database.py          # TursoDatabaseManager (per-user databases)
├── auth/                # Authentication module (COMPLETE - Phase 1)
│   ├── service.py       # OAuth business logic
│   ├── routes.py        # OAuth endpoints
│   ├── models.py        # Pydantic models
│   ├── crypto.py        # JWT generation and verification
│   ├── oauth_verifiers.py # Google + Apple token verification
│   └── dependencies.py  # FastAPI dependencies
├── add_ons/             # Add-ons module (TODO - Phase 2)
├── payments/            # Payment verification (TODO - Phase 3)
├── llm/                 # LLM proxy (TODO - Phase 4)
├── sync/                # Sync service (TODO - Phase 5)
└── embeddings/          # Fallback embeddings (TODO - Phase 6)
```

Each module follows the pattern: `models.py` → `service.py` → `routes.py` → `dependencies.py`.

### Configuration

All configuration is managed via Pydantic Settings in `app/config.py`:

**Required**:
- `TURSO_ORG_URL`, `TURSO_AUTH_TOKEN` - Turso database credentials
- `JWT_SECRET` - JWT signing secret

**OAuth (Required for authentication)**:
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` - Google OAuth credentials
- `APPLE_TEAM_ID`, `APPLE_KEY_ID`, `APPLE_PRIVATE_KEY` - Apple Sign In credentials

**Optional**:
- `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` - LLM providers (Phase 4)
- `APPLE_SHARED_SECRET`, `GOOGLE_SERVICE_ACCOUNT_JSON` - Payment verification (Phase 3)

**Access via**: `from app.config import settings`

### Logging

Structured JSON logging via `structlog`:

```python
import structlog
logger = structlog.get_logger()

logger.info("event_name", key1="value1", key2="value2")
logger.error("error_event", error=str(e), context="additional info")
```

All logs are JSON formatted for easy parsing and monitoring.

## Database Schema

### Master Database Schema

```sql
-- Users (OAuth identities)
CREATE TABLE users (
    user_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    provider_user_id TEXT NOT NULL,
    email TEXT,
    name TEXT,
    created_at INTEGER NOT NULL,
    UNIQUE(provider, provider_user_id)
);

-- User devices
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

-- User add-ons (subscriptions)
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
    auto_renew INTEGER DEFAULT 0,
    cancelled_at INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, add_on_type)
);

-- Purchase receipts
CREATE TABLE receipts (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    receipt_data TEXT NOT NULL,
    product_id TEXT NOT NULL,
    transaction_id TEXT NOT NULL,
    verified_at INTEGER NOT NULL
);

-- AI usage quota (anti-abuse)
CREATE TABLE ai_usage_quota (
    user_id TEXT NOT NULL,
    date TEXT NOT NULL,
    request_count INTEGER DEFAULT 0,
    last_reset_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, date)
);
```

### Per-User Database Schema

Each user database contains 7 tables:

1. **schema_version** - Migration tracking
2. **device_info** - DEPRECATED (devices now in master DB)
3. **synced_entries** - Encrypted journal entries with vector clocks
4. **synced_memories** - Encrypted memories (knowledge graph nodes)
5. **synced_tags** - Encrypted tags linked to entries
6. **entry_embeddings** - Fallback embeddings for old devices
7. **llm_usage** - LLM API usage tracking for transparency

All user data in `synced_*` tables is stored as encrypted BLOBs. The server cannot read content.

## API Endpoints

### Authentication (OAuth)
```
POST   /auth/oauth/signin       Sign in with Google or Apple
POST   /auth/refresh            Refresh access token
GET    /auth/devices            List user's devices
DELETE /auth/device/{id}        Delete device
GET    /auth/me                 Get current user info
```

### Add-Ons (Phase 2 - Not Implemented)
```
GET    /add-ons/status          Get user's add-ons
GET    /add-ons/features        Get feature flags
```

### Payments (Phase 3 - Not Implemented)
```
POST   /payments/verify         Verify App/Play Store receipt
POST   /payments/webhook/apple  Apple webhooks
POST   /payments/webhook/google Google webhooks
```

### LLM (Phase 4 - Not Implemented)
```
POST   /llm/generate            Zero-knowledge inference
GET    /llm/models              Available models
GET    /llm/usage               Usage statistics
```

### Sync (Phase 5 - Not Implemented)
```
POST   /sync/push               Push local changes
POST   /sync/pull               Pull remote changes
GET    /sync/status             Sync status
```

### Utility
```
GET    /                        API info
GET    /health                  Health check
```

## Common Patterns

### Adding a New Endpoint

1. Define Pydantic models in `models.py`:
```python
from pydantic import BaseModel

class MyRequest(BaseModel):
    field: str

class MyResponse(BaseModel):
    result: str
```

2. Implement business logic in `service.py`:
```python
class MyService:
    def do_something(self, user_id: str, request: MyRequest) -> MyResponse:
        # Business logic here
        return MyResponse(result="done")
```

3. Create route in `routes.py`:
```python
from fastapi import APIRouter, Depends

router = APIRouter(prefix="/my-module", tags=["my-module"])

@router.post("/endpoint")
async def my_endpoint(
    request: MyRequest,
    current_user: Tuple[str, str] = Depends(get_current_user)
):
    user_id, device_id = current_user
    # Call service layer
    return service.do_something(user_id, request)
```

4. Register router in `main.py`:
```python
from app.my_module.routes import router as my_router
app.include_router(my_router)
```

### Accessing Master Database

```python
from app.master_db import master_db_manager

# Get user by OAuth provider
user = master_db_manager.get_user_by_provider("google", "provider_user_id")

# Register device
master_db_manager.register_device(
    device_id="abc123",
    user_id=user_id,
    device_name="iPhone 15 Pro",
    platform="ios",
    app_version="1.0.0"
)

# Get user's add-ons
add_ons = master_db_manager.get_user_add_ons(user_id)
```

### Accessing User Database

```python
from app.database import db_manager

# Get user's database client
db = db_manager.get_user_db(user_id)

# Execute queries
result = db.execute("SELECT * FROM synced_entries WHERE is_deleted = 0")

# Access rows
for row in result.rows:
    entry_id = row[0]
    encrypted_data = row[1]
```

### Protected Routes

Use the `get_current_user` dependency for authenticated endpoints:

```python
from app.auth.dependencies import get_current_user

@router.get("/protected")
async def protected_route(
    current_user: Tuple[str, str] = Depends(get_current_user)
):
    user_id, device_id = current_user
    # Route logic here
```

The dependency automatically validates JWT tokens and extracts user_id + device_id.

### Checking Add-Ons

```python
from app.master_db import master_db_manager

# Check if user has AI add-on
if master_db_manager.is_add_on_active(user_id, "ai"):
    # Allow AI inference
    pass
else:
    raise HTTPException(status_code=403, detail="AI add-on required")
```

## Security Considerations

- **Never log sensitive data**: No tokens, keys, or unencrypted user content in logs
- **Validate all inputs**: Use Pydantic models with validation
- **OAuth token verification**: Always verify tokens with provider's public keys
- **Device verification**: Check device ownership before operations
- **Token rotation**: Both access and refresh tokens rotate on refresh
- **Zero-knowledge mode**: All user content encrypted client-side
- **Rate limiting**: Prevent abuse without creating paywalls

## Implementation Plan

See `IMPLEMENTATION_PLAN.md` for detailed implementation roadmap.

**Current Status**: Phase 1 Complete (OAuth Authentication)

**Next Steps**:
1. Phase 2: Add-Ons Management System
2. Phase 3: Payment Verification (App Store + Play Store)
3. Phase 4: LLM Inference Service (Zero-Knowledge)
4. Phase 5: Sync Service
5. Phase 6: Embeddings Service

## Deployment

Production deployment uses Docker Compose on a Hetzner VPS:

- Caddy reverse proxy handles SSL automatically
- Set `DEBUG=false` and `ENVIRONMENT=production` in production
- Disable `/docs` and `/redoc` in production (already configured)
- Configure CORS origins for production domains in `app/main.py`
- Monitor health endpoint: `GET /health`

## Cost Optimization

The architecture is optimized for low cost:

- 0-100 users: ~$4/month (Hetzner + Turso free tier)
- LRU cache keeps only active user databases in memory
- Embedded replicas reduce Turso API calls
- Cleanup script removes inactive replicas: `db_manager.cleanup_inactive_replicas(days=7)`

## Troubleshooting

### OAuth Issues
- Verify OAuth credentials in `.env`
- Check token verification logs: `grep oauth_token_verification_failed`
- Test with Google OAuth Playground or Apple JWT decoder

### Master Database Issues
- Verify master database exists: `turso db shell echolia_master`
- Check schema version: `SELECT * FROM schema_version;`
- Recreate if needed: Delete and restart app (auto-creates)

### Per-User Database Issues
- Verify user database exists: `turso db shell user_{uuid}`
- Check connection logs for "database_connection_failed"
- Schema migrations run automatically on first access

### Token Issues
- Tokens expire: 1 hour (access), 30 days (refresh)
- Check token payload: use JWT debugger at jwt.io
- Verify JWT_SECRET matches in .env and deployment
