# Echolia Backend

Privacy‑first backend for the Echolia desktop and mobile apps. It provides OAuth‑based authentication, a dual‑database architecture (master + per‑user Turso DBs), and end‑to‑end encrypted (E2EE) inference.

> High‑level architecture and detailed guidance live in `CLAUDE.md`. This `README` is a quickstart for running and working with the project.

## Features

- OAuth‑only auth (Google and Apple) with device tracking
- Master DB for identities, devices, add‑ons, receipts, and AI usage quota
- Per‑user embedded Turso databases for encrypted content (zero‑knowledge)
- E2EE inference API with usage limits and optional AI add‑on
- Planned: add‑ons management, payments, sync, and embeddings

## Tech Stack

- Python + FastAPI
- Turso / libSQL (master + per‑user DBs)
- Pydantic settings for configuration
- `structlog` for structured JSON logging
- `uv` for dependency and environment management

## Getting Started

### Prerequisites

- Python 3.11+ (recommended)
- [`uv`](https://docs.astral.sh/uv/) installed
- Turso account and database credentials

### Install Dependencies

```bash
uv sync
```

### Environment Variables

Configure the environment (e.g. via `.env`) with at least:

- `TURSO_ORG_URL`, `TURSO_AUTH_TOKEN`
- `JWT_SECRET`
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
- `APPLE_TEAM_ID`, `APPLE_KEY_ID`, `APPLE_PRIVATE_KEY`
- Optional: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`

See `app/config.py` and `CLAUDE.md` for the full list and details.

### Run the API (Local Dev)

```bash
uv run uvicorn app.main:app --reload
```

Then open:

- API base: http://localhost:8000
- Docs (dev only): http://localhost:8000/docs

### Tests

```bash
uv run pytest tests/
```

### Code Quality

```bash
uv run black app/
uv run ruff check app/
uv run mypy app/
```

## Docker (Production‑like)

You can run a production‑like stack via Docker:

```bash
docker-compose up -d
```

Rebuild after code changes:

```bash
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

The API is available at http://localhost:8000 behind the configured reverse proxy.

## Core Architecture

- `app/main.py` – FastAPI app, routers, CORS, startup/shutdown
- `app/config.py` – Pydantic settings and env configuration
- `app/master_db.py` – Master database (users, devices, add‑ons, AI quota)
- `app/database.py` – Per‑user embedded databases + LRU cache
- `app/auth/` – OAuth auth, JWTs, device management, dependencies
- `app/inference/` – E2EE inference tasks and provider integrations

Additional modules (`add_ons`, `payments`, `sync`, `embeddings`) are scaffolded for future phases.

## Key API Endpoints

- `POST /auth/oauth/signin` – Sign in with Google or Apple
- `POST /auth/refresh` – Refresh access token
- `GET /auth/devices` – List user devices
- `DELETE /auth/device/{id}` – Delete device
- `GET /auth/me` – Current user info
- `GET /inference/public-key` – Get server X25519 public key
- `POST /inference/execute` – Encrypted inference request
- `GET /inference/usage` – Inference usage stats
- `GET /health` – Health check

See `CLAUDE.md`, `app/main.py`, and module `routes.py` files for the full, current API surface.

## Security & Privacy

- Zero‑knowledge by design: user content is encrypted client‑side
- No passwords; OAuth‑only with provider token verification
- JWTs are device‑bound and rotated on refresh
- Access tokens expire after 1 hour; refresh tokens after 30 days
- No logging of tokens, keys, or unencrypted user data

