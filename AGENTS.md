# AGENTS.md

Guidance for AI agents working on this repository. Based on `CLAUDE.md` plus a quick scan of the current code (FastAPI app with master + per-user Turso DBs, OAuth auth, E2EE inference implemented).

## What This Project Is
- Privacy-first backend for Echolia apps: OAuth-only auth (Google/Apple), master DB for identities/add-ons/quotas, per-user DBs for encrypted data.
- Philosophy: indie, zero-knowledge, no paywalls; optional add-ons (Sync $2/mo, AI $3/mo, Supporter tips).
- Status: Phase 1 (OAuth + master DB) complete; E2EE inference live with free + AI tiers. Add-ons, payments, sync, embeddings planned/partial.

## Runbook (local, using uv)
- Install deps: `uv sync`
- Dev server: `uv run uvicorn app.main:app --reload` (or `uv run python -m app.main`)
- Tests: `uv run pytest tests/`
- Format/lint/typecheck: `uv run black app/`; `uv run ruff check app/`; `uv run mypy app/`
- Docker (prod-like): `docker-compose up -d`; rebuild with `docker-compose down && docker-compose build --no-cache && docker-compose up -d`

## Architecture Cheat Sheet
- Entry point: `app/main.py` wires routers for auth, add_ons, payments, inference; CORS for localhost/Tauri; structured logging via structlog.
- Config: `app/config.py` (Pydantic Settings) pulls env for Turso, JWT, OAuth, API keys, rate limits.
- Master DB: `app/master_db.py` manages users, devices, add-ons, receipts, AI quotas (direct Turso connections).
- Per-user DBs: `app/database.py` manages embedded replicas per user with LRU caching; commit via `db_manager.commit_and_sync`.
- Auth: `app/auth/` (models, service, routes, crypto, oauth_verifiers, dependencies). Flow: client sends provider `id_token` + device info to `/auth/oauth/signin`; server verifies token, registers user/device, creates per-user DB, returns access/refresh tokens.
- Inference (E2EE): `app/inference/` handles encrypted tasks (memory distillation, tagging, insight extraction) and uses LLM providers from `app/inference/providers/{anthropic,openai,google}.py`; quota tracked in master DB `ai_usage_quota` and per-user `llm_usage`.
- Add-ons/Payments: scaffolding present; see `CLAUDE.md` (Implementation Plan section) for planned routes and schemas.
- Inference/Sync/Embeddings: placeholders for future phases.

## Data Model (from CLAUDE.md)
- Master DB tables: `users`, `user_devices`, `user_add_ons`, `receipts`, `ai_usage_quota`.
- Per-user DB tables: `schema_version`, `device_info` (deprecated), `synced_entries`, `synced_memories`, `synced_tags`, `entry_embeddings`, `llm_usage`.

## API Highlights
- Auth: `POST /auth/oauth/signin`, `POST /auth/refresh`, `GET /auth/devices`, `DELETE /auth/device/{id}`, `GET /auth/me`.
- Inference (implemented, E2EE): `GET /inference/public-key`, `POST /inference/execute`, `GET /inference/usage` with free tier (10/day) vs AI add-on (5000/day; anti-abuse).
- Planned: add-ons (`/add-ons/status`, `/add-ons/features`), payments (`/payments/verify`, webhooks), sync (`/sync/push|pull|status`), embeddings, etc.

## Security & Privacy Norms
- Zero-knowledge: encrypted payloads only; never log tokens/keys/user content.
- JWTs include device fingerprinting; access tokens 1h, refresh 30d; deleting device invalidates tokens.
- Validate all inputs; use dependencies from `app/auth/dependencies.py` for protected routes.
- Respect add-on checks (use `master_db_manager.is_add_on_active`); rate limits are anti-abuse, not paywalls.

## Gotchas / Canonical Sources
- `CLAUDE.md` is the canonical high-level guide; older Markdown docs were removed to avoid drift—defer to code + CLAUDE.
- Turso embedded replicas are cached; remember to close connections on shutdown; master DB initialization happens on startup.
