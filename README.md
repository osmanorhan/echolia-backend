# Echolia Backend

Privacy-first sync and LLM inference service for Echolia desktop and mobile apps.

## Architecture

- **Database Strategy**: Database-per-user with Turso (LibSQL)
- **Hosting**: Designed for Hetzner VPS or similar
- **Stack**: Python FastAPI + Turso + Docker
- **Cost**: ~$4/month base + $0-29/month for 0-500+ users

## Features

### Phase 1: Core Auth & Sync (Implemented ✅)
- [x] Anonymous user registration
- [x] Device pairing and management
- [x] End-to-end encryption (E2EE) key exchange
- [x] JWT authentication
- [x] Database-per-user architecture
- [x] Embedded replicas for fast local access

### Phase 2-5: Coming Soon
- [ ] Entry sync (push/pull)
- [ ] Memory and tag sync
- [ ] Conflict resolution
- [ ] Zero-knowledge LLM proxy
- [ ] Payment processing (App Store / Play Store)
- [ ] Fallback embedding generation

## Quick Start

### Prerequisites

- Python 3.11+
- Docker and Docker Compose
- Turso account ([turso.tech](https://turso.tech))

### Setup

1. **Clone the repository**
   ```bash
   cd echolia-backend
   ```

2. **Create environment file**
   ```bash
   cp .env.example .env
   ```

3. **Configure Turso**

   Sign up at [turso.tech](https://turso.tech) and get your credentials:

   ```bash
   # Install Turso CLI
   brew install tursodatabase/tap/turso  # macOS
   # Or: curl -sSfL https://get.tur.so/install.sh | bash

   # Login
   turso auth login

   # Get organization URL
   turso org show

   # Create auth token
   turso auth token
   ```

   Update `.env`:
   ```env
   TURSO_ORG_URL=your-org.turso.io
   TURSO_AUTH_TOKEN=your_token_here
   ```

4. **Generate JWT secret**
   ```bash
   openssl rand -hex 32
   ```

   Add to `.env`:
   ```env
   JWT_SECRET=your_generated_secret
   ```

5. **Run with Docker Compose**
   ```bash
   docker-compose up -d
   ```

6. **Verify it's running**
   ```bash
   curl http://localhost:8000/health
   ```

### Local Development (Without Docker)

1. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the server**
   ```bash
   python -m app.main
   # Or: uvicorn app.main:app --reload
   ```

4. **Access the API**
   - API: http://localhost:8000
   - Docs: http://localhost:8000/docs (development only)
   - Health: http://localhost:8000/health

## API Endpoints

### Authentication

#### Register New User
```http
POST /auth/register
Content-Type: application/json

{
  "device_name": "My Desktop",
  "device_type": "desktop",
  "platform": "macos",
  "public_key": "-----BEGIN PUBLIC KEY-----\n..."
}
```

Response:
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "device_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer"
}
```

#### Pair New Device
```http
POST /auth/pair-device
Authorization: Bearer {access_token}
Content-Type: application/json

{
  "device_name": "My Phone",
  "device_type": "mobile",
  "platform": "ios",
  "public_key": "-----BEGIN PUBLIC KEY-----\n..."
}
```

#### List Devices
```http
GET /auth/devices
Authorization: Bearer {access_token}
```

#### Revoke Device
```http
DELETE /auth/device/{device_id}
Authorization: Bearer {access_token}
```

#### Refresh Token
```http
POST /auth/refresh
Content-Type: application/json

{
  "refresh_token": "eyJhbGciOiJIUzI1NiIs..."
}
```

## Database Architecture

### Per-User Database
Each user gets their own Turso database: `user_{user_id}.db`

Benefits:
- Perfect data isolation
- No risk of accidental data leaks
- Simple GDPR compliance (delete database = user gone)
- Selective embedded replica caching

### Schema (Per User Database)
```sql
-- Device information
device_info (device_id, device_name, device_type, platform, public_key, ...)

-- Synced data (all encrypted)
synced_entries (id, device_id, encrypted_data, version, ...)
synced_memories (id, encrypted_data, version, ...)
synced_tags (id, entry_id, encrypted_data, ...)

-- Optional: Fallback embeddings
entry_embeddings (entry_id, embedding, model_version, ...)

-- LLM usage tracking
llm_usage (id, model, input_tokens, output_tokens, cost_usd, ...)
```

## Security & Privacy

### End-to-End Encryption
- Client generates keypair on device
- Private key NEVER leaves device
- Server only stores public keys
- All user data encrypted before upload

### Zero-Knowledge Architecture
- Server never sees unencrypted user data
- Even LLM proxy processes encrypted requests
- No content logging
- Minimal metadata retention

### Authentication
- JWT tokens with device fingerprinting
- Short-lived access tokens (1 hour)
- Long-lived refresh tokens (30 days)
- Device-based revocation

## Deployment

### Hetzner VPS Deployment

1. **Provision VPS**
   - Sign up at [hetzner.com](https://www.hetzner.com)
   - Create CX23 VPS (€3.49/month)
   - Choose Ubuntu 22.04

2. **Install Docker**
   ```bash
   curl -fsSL https://get.docker.com -o get-docker.sh
   sudo sh get-docker.sh
   sudo usermod -aG docker $USER
   ```

3. **Clone and configure**
   ```bash
   git clone https://github.com/your-org/echolia-backend.git
   cd echolia-backend
   cp .env.example .env
   nano .env  # Configure environment variables
   ```

4. **Deploy**
   ```bash
   docker-compose up -d
   ```

5. **Configure domain** (Optional)
   - Point your domain to VPS IP
   - Update `Caddyfile` with your domain
   - Caddy handles SSL automatically

### Cost Breakdown

#### 0-100 Users (Free Tier)
- Hetzner CX23: $3.79/month
- Turso: $0 (free tier, 100 DBs)
- **Total: $3.79/month**

#### 100-500 Users
- Hetzner CX23: $3.79/month
- Turso Scaler: $24/month (500 DBs)
- **Total: $27.79/month**

#### 500+ Users
- Hetzner CPX21: $8.49/month
- Turso Scaler + Unlimited: $29/month
- **Total: $37.49/month**

## Development

### Project Structure
```
echolia-backend/
├── app/
│   ├── main.py              # FastAPI application
│   ├── config.py            # Configuration
│   ├── database.py          # Turso database manager
│   ├── auth/                # Authentication module
│   │   ├── models.py
│   │   ├── service.py
│   │   ├── routes.py
│   │   ├── crypto.py
│   │   └── dependencies.py
│   ├── sync/                # Sync module (coming soon)
│   ├── llm/                 # LLM module (coming soon)
│   ├── payments/            # Payments module (coming soon)
│   └── embeddings/          # Embeddings module (coming soon)
├── migrations/              # Database migrations
├── tests/                   # Test suite
├── Dockerfile
├── docker-compose.yml
├── Caddyfile
└── requirements.txt
```

### Running Tests
```bash
pytest tests/
```

### Code Style
```bash
# Format code
black app/

# Lint
ruff check app/

# Type checking
mypy app/
```

## Monitoring

### Health Check
```bash
curl http://localhost:8000/health
```

### Logs
```bash
# Docker logs
docker-compose logs -f api

# Structured logs (JSON)
docker-compose logs api | jq '.'
```

### Metrics to Monitor
- Active users per day
- Sync operations per minute
- Database count (Turso dashboard)
- Disk usage for embedded replicas
- API response times

## Troubleshooting

### Database Connection Issues
```bash
# Verify Turso credentials
turso auth show

# Test connection
turso db shell user_test
```

### Docker Issues
```bash
# Rebuild containers
docker-compose down
docker-compose build --no-cache
docker-compose up -d

# Check logs
docker-compose logs -f
```

### Permission Issues
```bash
# Fix data directory permissions
sudo chown -R $USER:$USER data/
```

## Roadmap

### Phase 1: Core Auth & Sync ✅
- [x] Authentication system
- [x] Database-per-user architecture
- [ ] Entry sync implementation

### Phase 2: Advanced Sync
- [ ] Memory sync
- [ ] Tag sync
- [ ] Conflict resolution (CRDT)
- [ ] Delta sync optimization

### Phase 3: LLM Service
- [ ] Zero-knowledge proxy
- [ ] Provider abstraction
- [ ] Streaming support
- [ ] Rate limiting & quotas

### Phase 4: Payments
- [ ] App Store receipt validation
- [ ] Play Store receipt validation
- [ ] Subscription management
- [ ] Webhook handlers

### Phase 5: Embeddings
- [ ] Fallback embedding service
- [ ] Device capability detection

## Contributing

This is a private project for Echolia apps. If you're part of the team:

1. Create a feature branch
2. Make your changes
3. Add tests
4. Submit a pull request

## License

Proprietary - All rights reserved

## Support

For issues or questions:
- Open an issue on GitHub
- Contact: [your-email@example.com]

---

Built with ❤️ for privacy-conscious users
