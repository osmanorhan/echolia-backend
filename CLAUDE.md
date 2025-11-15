# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Echolia Backend is a privacy-first sync and LLM inference service for the Echolia desktop and mobile apps. It uses a **database-per-user architecture** with Turso (LibSQL), where each user gets their own isolated database for perfect data isolation and zero-knowledge operations.

**Current Status**: Phase 1 complete (~20% overall). Authentication system and database infrastructure are fully operational. Sync, LLM, payments, and embeddings services are planned but not yet implemented.

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

### Legacy Setup (without uv)
```bash
# Setup virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run development server
uvicorn app.main:app --reload
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
# List all user databases
turso db list | grep user_

# Access a specific user's database
turso db shell user_<uuid>

# Check schema version
turso db shell user_<uuid> "SELECT * FROM schema_version;"
```

## Architecture & Key Concepts

### Database-Per-User Pattern

The most critical architectural decision is the **database-per-user model**:

- Each user gets `user_{user_id}.db` in Turso
- Perfect data isolation (no multi-tenant queries)
- GDPR compliance: delete database = user gone
- Embedded replicas cache active user databases locally on VPS
- LRU cache (`@lru_cache(maxsize=100)`) manages connections to most active users

**Key files**:
- `app/database.py` - `TursoDatabaseManager` class handles all database operations
- Database connections are lazily created via `get_user_db(user_id)`
- Schema migrations run automatically on first database access
- Initial schema (v001) creates 7 tables per user database

### Authentication & E2EE

Zero-knowledge authentication with device-based security:

- Anonymous registration (no email/password)
- Each device generates RSA keypair locally
- Private keys NEVER leave device
- Server only stores public keys for E2EE key exchange
- JWT tokens with device fingerprinting
- Access tokens expire in 1 hour, refresh tokens in 30 days
- Device revocation immediately invalidates tokens

**Key files**:
- `app/auth/service.py` - `AuthService` contains all auth business logic
- `app/auth/crypto.py` - JWT and public key validation functions
- `app/auth/models.py` - Pydantic models for requests/responses
- `app/auth/routes.py` - FastAPI endpoints
- `app/auth/dependencies.py` - JWT verification dependency for protected routes

### Module Structure

The codebase follows a modular FastAPI structure:

```
app/
├── main.py              # FastAPI app, middleware, startup/shutdown
├── config.py            # Pydantic settings from environment variables
├── database.py          # TursoDatabaseManager singleton
├── auth/                # Authentication module (COMPLETE)
│   ├── service.py       # Business logic
│   ├── routes.py        # API endpoints
│   ├── models.py        # Pydantic models
│   ├── crypto.py        # JWT and key validation
│   └── dependencies.py  # FastAPI dependencies
├── sync/                # Sync service (TODO - Phase 2)
├── llm/                 # LLM proxy (TODO - Phase 3)
├── payments/            # Payment validation (TODO - Phase 4)
└── embeddings/          # Fallback embeddings (TODO - Phase 5)
```

Each module follows the same pattern: `models.py` → `service.py` → `routes.py` → `dependencies.py`.

### Configuration

All configuration is managed via Pydantic Settings in `app/config.py`:

- Environment variables loaded from `.env` file
- Required: `TURSO_ORG_URL`, `TURSO_AUTH_TOKEN`, `JWT_SECRET`
- Optional: LLM API keys, payment credentials (for future phases)
- Access via `from app.config import settings`

### Logging

Structured JSON logging via `structlog`:

```python
import structlog
logger = structlog.get_logger()

logger.info("event_name", key1="value1", key2="value2")
logger.error("error_event", error=str(e), context="additional info")
```

All logs are JSON formatted for easy parsing and monitoring.

## Database Schema (Per User)

Each user database contains 7 tables:

1. **schema_version** - Migration tracking
2. **device_info** - User's paired devices with public keys
3. **synced_entries** - Encrypted journal entries with vector clocks
4. **synced_memories** - Encrypted memories (knowledge graph nodes)
5. **synced_tags** - Encrypted tags linked to entries
6. **entry_embeddings** - Fallback embeddings for old devices
7. **llm_usage** - LLM API usage tracking for billing

All user data in `synced_*` tables is stored as encrypted BLOBs. The server cannot read content.

## Testing Strategy

Current tests are basic unit tests (`tests/test_auth.py`). When adding new features:

1. Write Pydantic model tests (validate schemas)
2. Write service layer tests (business logic)
3. Write integration tests (full API flow)

Use `pytest-asyncio` for async tests:
```python
@pytest.mark.asyncio
async def test_register_user():
    # Test async functions
    pass
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
    def do_something(self, db: Client, request: MyRequest) -> MyResponse:
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
    current_user: str = Depends(get_current_user)
):
    # Call service layer
    return service.do_something(db, request)
```

4. Register router in `main.py`:
```python
from app.my_module.routes import router as my_router
app.include_router(my_router)
```

### Accessing User Database

Always use the database manager:

```python
from app.database import db_manager

# Get user's database client
db = db_manager.get_user_db(user_id)

# Execute queries
result = db.execute("SELECT * FROM device_info WHERE device_id = ?", [device_id])

# Access rows
for row in result.rows:
    device_id = row[0]
    device_name = row[1]
```

### Protected Routes

Use the `get_current_user` dependency for authenticated endpoints:

```python
from app.auth.dependencies import get_current_user

@router.get("/protected")
async def protected_route(current_user: str = Depends(get_current_user)):
    user_id = current_user  # UUID string
    # Route logic here
```

The dependency automatically validates JWT tokens and extracts user_id.

## API Design Conventions

- Use Pydantic models for all request/response schemas
- Return structured JSON responses, not plain strings
- Use appropriate HTTP status codes (200, 400, 401, 404, 500)
- Use `HTTPException` for errors: `raise HTTPException(status_code=400, detail="Error message")`
- All timestamps are Unix timestamps (seconds since epoch)
- All IDs are UUIDs (generated with `uuid.uuid4()`)

## Security Considerations

- **Never log sensitive data**: No tokens, keys, or unencrypted user content in logs
- **Validate all inputs**: Use Pydantic models with validation
- **Public key validation**: Always call `validate_public_key()` before storing keys
- **Device verification**: Check device ownership before operations
- **Token rotation**: Both access and refresh tokens rotate on refresh
- The server operates in **zero-knowledge mode**: all user content is encrypted client-side

## Future Implementation Notes

### Phase 2: Sync Service (Next Priority)
- Implement delta sync with vector clocks for conflict resolution
- Support push/pull for entries, memories, and tags
- Use tombstones for soft deletes
- All synced data arrives pre-encrypted from clients

### Phase 3: LLM Proxy
- Zero-knowledge proxy: ephemeral key decryption in memory
- Support Anthropic, OpenAI, and Google providers
- Track token usage per user for billing
- No logging of requests or responses

### Phase 4: Payments
- Validate App Store and Play Store receipts
- Master database for subscription status (outside user databases)
- Webhook handlers for subscription changes

### Phase 5: Embeddings
- Fallback embedding generation for devices without local models
- Store in `entry_embeddings` table per user

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

### Turso Connection Issues
- Verify credentials: `turso auth show`
- Test connection: `turso db shell user_test`
- Check logs for "database_connection_failed" events

### Schema Issues
- Schema migrations run automatically on first access
- Check version: `SELECT * FROM schema_version;`
- Manual migration: Call `db_manager._ensure_schema(client, user_id)`

### Token Issues
- Tokens expire: 1 hour (access), 30 days (refresh)
- Check token payload: use JWT debugger at jwt.io
- Verify JWT_SECRET matches in .env and deployment
