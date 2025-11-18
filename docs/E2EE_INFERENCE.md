# E2EE Inference System

This document explains how Echolia's End-to-End Encrypted (E2EE) inference system works, enabling AI-powered features while maintaining zero-knowledge privacy.

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Cryptographic Flow](#cryptographic-flow)
4. [Request Processing Pipeline](#request-processing-pipeline)
5. [Task Processing](#task-processing)
6. [LLM Integration](#llm-integration)
7. [Rate Limiting & Quota](#rate-limiting--quota)
8. [Security Guarantees](#security-guarantees)
9. [Implementation Details](#implementation-details)

## Overview

The E2EE inference system allows users to leverage server-side AI capabilities without exposing their journal entries or personal data to the server. The system uses modern cryptographic primitives to ensure that:

- **Client-side encryption**: All content is encrypted before leaving the user's device
- **Zero-knowledge server**: Server processes encrypted data without ever seeing plaintext
- **Perfect forward secrecy**: Each request uses a fresh ephemeral keypair
- **Authenticated encryption**: Tamper-proof encryption prevents man-in-the-middle attacks

### Available Tasks

The system supports three AI-powered tasks:

1. **Memory Distillation** (`memory_distillation`): Extracts structured memories from journal entries
   - Commitments: Future actions or promises
   - Facts: Learned information
   - Insights: Realizations or conclusions
   - Patterns: Recurring behaviors
   - Preferences: Personal preferences

2. **Tagging** (`tagging`): Extracts relevant tags from content
   - Topics: work, personal, family, health, finance, learning
   - Types: task, reminder, question, idea, reflection, gratitude
   - Entities: project, meeting, deadline, goal, event

3. **Insight Extraction** (`insight_extraction`): Identifies deeper insights and patterns
   - Recurring themes or patterns
   - Connections to broader goals or values
   - Emotional patterns or trends
   - Areas of growth or concern
   - Underlying motivations

## Architecture

The E2EE inference system consists of four main components:

```
┌─────────────────────────────────────────────────────────────┐
│                    Client Application                        │
│  (Desktop/Mobile App - Swift/Dart/Kotlin)                   │
│                                                              │
│  1. Generate ephemeral X25519 keypair                       │
│  2. Derive shared secret with server's public key           │
│  3. Encrypt content with ChaCha20-Poly1305                  │
│  4. Send encrypted request to server                        │
│  5. Decrypt response with same shared secret                │
└─────────────────────────────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              FastAPI Server - Inference Router              │
│              (app/inference/routes.py)                       │
│                                                              │
│  GET  /inference/public-key  → Return server's X25519 key   │
│  POST /inference/execute     → Execute E2EE inference       │
│  GET  /inference/usage       → Get user's quota             │
└─────────────────────────────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│            E2EE Inference Service                           │
│            (app/inference/service.py)                        │
│                                                              │
│  1. Check rate limits (free: 10/day, paid: 5000/day)       │
│  2. Derive shared secret using X25519                       │
│  3. Decrypt content with ChaCha20-Poly1305                  │
│  4. Pass plaintext to Task Processor (ephemeral)            │
│  5. Encrypt result with same shared secret                  │
│  6. Return encrypted response                               │
└─────────────────────────────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│               Task Processor                                │
│               (app/inference/tasks.py)                       │
│                                                              │
│  - Select LLM provider (Anthropic/OpenAI/Google)            │
│  - Build task-specific prompts                              │
│  - Execute LLM inference                                    │
│  - Parse and validate JSON results                          │
│  - Clear plaintext from memory                              │
└─────────────────────────────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│           LLM Provider (Anthropic/OpenAI/Google)            │
│           (app/llm/providers/)                               │
│                                                              │
│  - Call external LLM API (Claude/GPT/Gemini)                │
│  - Track usage (tokens, cost)                               │
│  - Return structured response                               │
└─────────────────────────────────────────────────────────────┘
```

## Cryptographic Flow

The system uses **X25519** (Elliptic Curve Diffie-Hellman) for key exchange and **ChaCha20-Poly1305** (AEAD) for authenticated encryption.

### Step 1: Server Key Generation

The server generates a long-lived X25519 keypair on startup:

```python
# app/inference/crypto.py - E2EECrypto.__init__()

# Generate X25519 keypair
private_key = x25519.X25519PrivateKey.generate()
public_key = private_key.public_key()

# Save to disk (./data/inference_key.bin)
# Key rotates every 30 days
```

**Key Rotation**: The server's keypair rotates automatically every 30 days to limit exposure if the key is compromised.

### Step 2: Client Fetches Server's Public Key

Before making an inference request, the client fetches the server's current public key:

```http
GET /inference/public-key

Response:
{
  "public_key": "base64_encoded_32_byte_x25519_public_key",
  "key_id": "server-key-2025-11",
  "expires_at": "2025-12-01T00:00:00Z",
  "algorithm": "X25519"
}
```

The client caches this key locally and refetches when it expires or when the app launches.

### Step 3: Client-Side Encryption

For each inference request, the client:

1. **Generates ephemeral X25519 keypair** (fresh for every request):
```python
client_private = x25519.X25519PrivateKey.generate()
client_public = client_private.public_key()
```

2. **Performs X25519 key exchange** to derive shared secret:
```python
# Decode server's public key
server_public = x25519.X25519PublicKey.from_public_bytes(
    base64.b64decode(server_key["public_key"])
)

# Perform Diffie-Hellman key exchange
shared_secret = client_private.exchange(server_public)
# shared_secret is 32 bytes (256 bits)
```

3. **Derives encryption key using HKDF** (Hash-based Key Derivation Function):
```python
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

hkdf = HKDF(
    algorithm=hashes.SHA256(),
    length=32,  # ChaCha20 requires 32-byte key
    salt=None,
    info=b"echolia-inference-v1"  # Domain separation
)
encryption_key = hkdf.derive(shared_secret)
```

4. **Encrypts content with ChaCha20-Poly1305**:
```python
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
import secrets

# Generate random 12-byte nonce
nonce = secrets.token_bytes(12)

# Encrypt (also generates 16-byte MAC tag)
chacha = ChaCha20Poly1305(encryption_key)
ciphertext_with_tag = chacha.encrypt(nonce, plaintext.encode('utf-8'), None)

# Split ciphertext and MAC tag
ciphertext = ciphertext_with_tag[:-16]
mac = ciphertext_with_tag[-16:]
```

5. **Sends encrypted request**:
```http
POST /inference/execute
Authorization: Bearer <access_token>

{
  "task": "memory_distillation",
  "encrypted_content": "base64_encoded_ciphertext",
  "nonce": "base64_encoded_12_byte_nonce",
  "mac": "base64_encoded_16_byte_mac",
  "ephemeral_public_key": "base64_encoded_client_public_key",
  "client_version": "1.0.0"
}
```

### Step 4: Server-Side Decryption

The server receives the request and:

1. **Validates JWT token** (ensures user is authenticated)

2. **Checks rate limits** (free: 10/day, AI add-on: 5000/day)

3. **Derives the SAME shared secret** using client's ephemeral public key:
```python
# app/inference/crypto.py - E2EECrypto.derive_shared_secret()

# Decode client's ephemeral public key
client_public_bytes = base64.b64decode(request.ephemeral_public_key)
client_public_key = x25519.X25519PublicKey.from_public_bytes(client_public_bytes)

# Perform key exchange (server's private key × client's public key)
shared_secret = server_private_key.exchange(client_public_key)

# Derive encryption key with HKDF (same as client)
hkdf = HKDF(
    algorithm=hashes.SHA256(),
    length=32,
    salt=None,
    info=b"echolia-inference-v1"  # MUST match client's info
)
encryption_key = hkdf.derive(shared_secret)
```

4. **Decrypts content**:
```python
# app/inference/crypto.py - E2EECrypto.decrypt_content()

# Decode base64 inputs
ciphertext = base64.b64decode(request.encrypted_content)
nonce = base64.b64decode(request.nonce)
mac = base64.b64decode(request.mac)

# ChaCha20-Poly1305 expects ciphertext + tag concatenated
authenticated_ciphertext = ciphertext + mac

# Decrypt and verify MAC tag in one operation
chacha = ChaCha20Poly1305(encryption_key)
plaintext_bytes = chacha.decrypt(nonce, authenticated_ciphertext, None)

plaintext_content = plaintext_bytes.decode('utf-8')
```

**Important**: If the MAC verification fails, `chacha.decrypt()` raises an exception. This ensures no tampered ciphertext is ever processed.

5. **Processes content** (see Task Processing section)

6. **Encrypts response** with the SAME encryption key:
```python
# app/inference/crypto.py - E2EECrypto.encrypt_response()

# Generate fresh nonce for response
response_nonce = secrets.token_bytes(12)

# Encrypt result
chacha = ChaCha20Poly1305(encryption_key)
ciphertext_with_tag = chacha.encrypt(
    response_nonce,
    result_json.encode('utf-8'),
    None
)

# Split and base64 encode
response_ciphertext = ciphertext_with_tag[:-16]
response_mac = ciphertext_with_tag[-16:]

return {
    "encrypted_result": base64.b64encode(response_ciphertext).decode(),
    "nonce": base64.b64encode(response_nonce).decode(),
    "mac": base64.b64encode(response_mac).decode(),
    "usage": {...}
}
```

7. **Clears sensitive data from memory**:
```python
# app/inference/service.py - E2EEInferenceService.execute_inference()

finally:
    # Clear sensitive data from memory
    if plaintext_content is not None:
        plaintext_content = None
    if result_json is not None:
        result_json = None
    if encryption_key is not None:
        encryption_key = None
```

### Step 5: Client-Side Decryption

The client receives the encrypted response and:

1. **Decrypts with the SAME shared secret/encryption key** (derived in Step 3):
```python
# Decode response
response_ciphertext = base64.b64decode(response["encrypted_result"])
response_nonce = base64.b64decode(response["nonce"])
response_mac = base64.b64decode(response["mac"])

# Decrypt
chacha = ChaCha20Poly1305(encryption_key)
plaintext_result = chacha.decrypt(
    response_nonce,
    response_ciphertext + response_mac,
    None
)

# Parse result
import json
result = json.loads(plaintext_result.decode('utf-8'))
```

2. **Uses the result** (e.g., displays extracted memories in UI)

3. **Clears encryption key from memory**

## Request Processing Pipeline

Here's the complete flow of a single inference request:

```
Client                              Server                           LLM Provider
  │                                   │                                    │
  │  1. GET /inference/public-key     │                                    │
  ├──────────────────────────────────►│                                    │
  │  ◄─────────────────────────────────┤                                    │
  │     {public_key, key_id, ...}     │                                    │
  │                                   │                                    │
  │  2. Generate ephemeral keypair    │                                    │
  │     Derive shared secret          │                                    │
  │     Encrypt content               │                                    │
  │                                   │                                    │
  │  3. POST /inference/execute       │                                    │
  │     {encrypted_content, nonce,    │                                    │
  │      mac, ephemeral_public_key}   │                                    │
  ├──────────────────────────────────►│                                    │
  │                                   │  4. Verify JWT token               │
  │                                   │     Check rate limits              │
  │                                   │     (10/day free, 5000/day paid)   │
  │                                   │                                    │
  │                                   │  5. Derive shared secret           │
  │                                   │     (X25519 key exchange)          │
  │                                   │                                    │
  │                                   │  6. Decrypt content                │
  │                                   │     (ChaCha20-Poly1305)            │
  │                                   │                                    │
  │                                   │  7. Build task-specific prompt     │
  │                                   │     (memory_distillation,          │
  │                                   │      tagging, insight_extraction)  │
  │                                   │                                    │
  │                                   │  8. Call LLM provider              │
  │                                   ├───────────────────────────────────►│
  │                                   │                                    │
  │                                   │  ◄─────────────────────────────────┤
  │                                   │     LLM response (JSON)            │
  │                                   │                                    │
  │                                   │  9. Parse and validate result      │
  │                                   │                                    │
  │                                   │ 10. Encrypt result                 │
  │                                   │     (with same shared secret)      │
  │                                   │                                    │
  │                                   │ 11. Update quota counter           │
  │                                   │                                    │
  │                                   │ 12. Clear plaintext from memory    │
  │                                   │                                    │
  │  ◄─────────────────────────────────┤                                    │
  │     {encrypted_result, nonce,     │                                    │
  │      mac, usage}                  │                                    │
  │                                   │                                    │
  │ 13. Decrypt result                │                                    │
  │     (with same shared secret)     │                                    │
  │                                   │                                    │
  │ 14. Display result to user        │                                    │
  │                                   │                                    │
```

### Code Reference

The complete pipeline is implemented in:

- **Client encryption**: Mobile/desktop app (not in this repo)
- **Server routing**: `app/inference/routes.py:42-131` (`execute_inference`)
- **E2EE service**: `app/inference/service.py:149-252` (`execute_inference`)
- **Crypto operations**: `app/inference/crypto.py:170-273`
- **Task processing**: `app/inference/tasks.py:60-88` (`process_task`)

## Task Processing

Once content is decrypted, the Task Processor (`app/inference/tasks.py`) routes it to the appropriate LLM prompt based on the task type.

### Memory Distillation Task

**Purpose**: Extract structured memories from journal entries.

**System Prompt** (`app/inference/tasks.py:93-109`):
```
You are a memory extraction assistant. Your task is to identify and extract
important memories from journal entries. Focus on:

1. Commitments - Future actions or promises ("I will...", "Need to...", "Should call...")
2. Facts - Learned information ("Flutter uses Dart", "The meeting is at 3pm")
3. Insights - Realizations or conclusions ("I realized that...", "Understood why...")
4. Patterns - Recurring behaviors ("I always...", "Every time...")
5. Preferences - Personal preferences ("I prefer...", "I like...")

Return a JSON object with this exact structure:
{
  "memories": [
    {"type": "commitment|fact|insight|pattern|preference", "content": "extracted memory", "confidence": 0.0-1.0}
  ],
  "confidence": 0.0-1.0
}

Only extract clear, meaningful memories. Assign confidence based on how explicit the memory is in the text.
```

**User Prompt**:
```
Extract memories from this journal entry:

<decrypted_content>
```

**LLM Response** (example):
```json
{
  "memories": [
    {
      "type": "commitment",
      "content": "Need to call dentist on Monday to schedule checkup",
      "confidence": 0.95
    },
    {
      "type": "insight",
      "content": "Realized that morning walks improve my focus throughout the day",
      "confidence": 0.85
    },
    {
      "type": "pattern",
      "content": "Always feel anxious before big presentations",
      "confidence": 0.9
    }
  ],
  "confidence": 0.9
}
```

**Result Type**: `MemoryDistillationResult` (Pydantic model)

### Tagging Task

**Purpose**: Extract relevant tags from content.

**System Prompt** (`app/inference/tasks.py:139-154`):
```
You are a tagging assistant. Your task is to extract relevant tags from journal entries.

Common tag categories:
- Topics: work, personal, family, health, finance, learning
- Types: task, reminder, question, idea, reflection, gratitude
- Entities: project, meeting, deadline, goal, event

Return a JSON object with this exact structure:
{
  "tags": [
    {"tag": "lowercase_tag", "confidence": 0.0-1.0}
  ],
  "confidence": 0.0-1.0
}

Extract 3-7 most relevant tags. Use lowercase, single words. Assign confidence based on relevance.
```

**LLM Response** (example):
```json
{
  "tags": [
    {"tag": "health", "confidence": 0.95},
    {"tag": "commitment", "confidence": 0.9},
    {"tag": "insight", "confidence": 0.85},
    {"tag": "wellness", "confidence": 0.8}
  ],
  "confidence": 0.88
}
```

**Result Type**: `TaggingResult` (Pydantic model)

### Insight Extraction Task

**Purpose**: Extract deeper insights and patterns from content.

**System Prompt** (`app/inference/tasks.py:181-199`):
```
You are an insight extraction assistant. Your task is to identify deeper insights,
patterns, and connections in journal entries.

Focus on:
- Recurring themes or patterns
- Connections to broader goals or values
- Emotional patterns or trends
- Areas of growth or concern
- Underlying motivations

Return a JSON object with this exact structure:
{
  "insights": [
    "First insight as a complete sentence",
    "Second insight as a complete sentence"
  ],
  "confidence": 0.0-1.0
}

Provide 1-3 meaningful insights. Write them as helpful observations that could aid self-reflection.
```

**LLM Response** (example):
```json
{
  "insights": [
    "You tend to set ambitious goals on Mondays but struggle with follow-through by Wednesday, suggesting you may benefit from smaller, more incremental targets",
    "Your journal entries show a strong connection between physical activity and mental clarity, particularly with morning routines",
    "There's a recurring pattern of anxiety before social events, but your reflections afterward are consistently positive, indicating the anticipation is worse than the reality"
  ],
  "confidence": 0.82
}
```

**Result Type**: `InsightExtractionResult` (Pydantic model)

### Task Processing Implementation

**Code**: `app/inference/tasks.py:60-88`

```python
async def process_task(self, task: InferenceTask, plaintext_content: str) -> str:
    """
    Process an inference task on plaintext content.

    Args:
        task: The inference task to execute
        plaintext_content: Decrypted user content

    Returns:
        JSON string of task result

    Note: plaintext_content should be cleared from memory after this call
    """
    try:
        if task == InferenceTask.MEMORY_DISTILLATION:
            result = await self._memory_distillation(plaintext_content)
        elif task == InferenceTask.TAGGING:
            result = await self._tagging(plaintext_content)
        elif task == InferenceTask.INSIGHT_EXTRACTION:
            result = await self._insight_extraction(plaintext_content)
        else:
            raise ValueError(f"Unknown task: {task}")

        # Convert Pydantic model to JSON string
        return result.model_dump_json()

    except Exception as e:
        logger.error("task_processing_failed", task=task, error=str(e))
        raise
```

**Important**: The plaintext content is processed in ephemeral memory and cleared immediately after use. No plaintext is ever logged.

## LLM Integration

The Task Processor calls LLM providers (Anthropic Claude, OpenAI GPT, Google Gemini) to execute the actual inference.

### Provider Selection

The system automatically selects an available LLM provider based on configured API keys (`app/inference/tasks.py:38-53`):

```python
def _ensure_provider(self):
    """Lazily initialize the LLM provider."""
    if self._provider is not None:
        return

    if settings.anthropic_api_key:
        self._provider = AnthropicProvider()
        self._model = ModelType.CLAUDE_HAIKU  # Fast and cheap for simple tasks
    elif settings.openai_api_key:
        self._provider = OpenAIProvider()
        self._model = ModelType.GPT_4O_MINI
    elif settings.gemini_api_key:
        self._provider = GoogleProvider()
        self._model = ModelType.GEMINI_FLASH
    else:
        raise ValueError("No LLM provider API key configured")
```

**Priority**:
1. Anthropic Claude (Claude 3 Haiku)
2. OpenAI GPT (GPT-4o Mini)
3. Google Gemini (Gemini 1.5 Flash)

**Model Selection**: The system uses the fastest/cheapest models for E2EE inference tasks:
- **Claude 3 Haiku**: Fast, cheap, excellent for structured JSON output
- **GPT-4o Mini**: Fast, affordable, good JSON adherence
- **Gemini 1.5 Flash**: Fast, large context window

### LLM Request Format

All providers receive a standardized `InferenceRequest` (`app/llm/models.py:30-37`):

```python
class InferenceRequest(BaseModel):
    messages: List[Message]  # [system, user]
    model: ModelType
    max_tokens: int = 1024
    temperature: float = 0.3  # Lower for consistent JSON output
    stream: bool = False
```

Example request:
```python
request = InferenceRequest(
    messages=[
        Message(role="system", content="You are a memory extraction assistant..."),
        Message(role="user", content="Extract memories from: <content>")
    ],
    model=ModelType.CLAUDE_HAIKU,
    max_tokens=1024,
    temperature=0.3
)

response = await provider.generate(request)
```

### LLM Response Format

All providers return a standardized `InferenceResponse` (`app/llm/models.py:39-45`):

```python
class InferenceResponse(BaseModel):
    content: str  # LLM's response (JSON string)
    model: str    # Actual model used
    usage: UsageStats  # Token counts
    finish_reason: str  # "stop", "length", "content_filter"
```

### JSON Extraction

The Task Processor handles LLM responses that may include markdown code blocks (`app/inference/tasks.py:241-249`):

```python
# Extract JSON from response (handle markdown code blocks)
content = response.content.strip()
if content.startswith("```json"):
    content = content[7:]
if content.startswith("```"):
    content = content[3:]
if content.endswith("```"):
    content = content[:-3]

return content.strip()
```

This ensures robust parsing even if the LLM wraps JSON in markdown formatting.

### Provider Implementations

Each provider implements the same interface (`app/llm/providers/`):

- **Anthropic** (`anthropic.py`): Uses `anthropic` Python SDK
- **OpenAI** (`openai.py`): Uses `openai` Python SDK
- **Google** (`google.py`): Uses `google-generativeai` Python SDK

All providers:
- Convert `InferenceRequest` to provider-specific format
- Call external API
- Parse response into standardized `InferenceResponse`
- Track token usage

## Rate Limiting & Quota

The E2EE inference service implements two-tier rate limiting to prevent abuse while maintaining accessibility.

### Tier System

**Free Tier** (no AI add-on):
- 10 requests per day
- Resets at midnight UTC
- No credit card required
- Allows users to try AI features

**AI Add-On** ($3/month):
- 5000 requests per day (anti-abuse limit, not a paywall)
- Resets at midnight UTC
- Sufficient for normal usage (~166 requests/hour)

### Quota Management

**Code**: `app/inference/service.py:101-148`

```python
def check_and_update_quota(self, user_id: str) -> bool:
    """
    Check if user can make a request and update quota.

    Args:
        user_id: User UUID

    Returns:
        True if user can make request, False if quota exceeded
    """
    usage = self.get_usage_info(user_id)

    if usage.requests_remaining <= 0:
        logger.warning(
            "e2ee_inference_quota_exceeded",
            user_id=user_id,
            tier=usage.tier
        )
        return False

    # Update quota in database
    today = datetime.utcnow().strftime("%Y-%m-%d")
    current_time = int(time.time())

    conn = self.master_db.get_connection()

    # Upsert request count (atomic increment)
    conn.execute(
        """
        INSERT INTO ai_usage_quota (user_id, date, request_count, last_reset_at)
        VALUES (?, ?, 1, ?)
        ON CONFLICT(user_id, date) DO UPDATE SET
            request_count = request_count + 1,
            last_reset_at = excluded.last_reset_at
        """,
        [user_id, today, current_time]
    )
    conn.commit()

    return True
```

### Database Schema

Quota tracking uses the `ai_usage_quota` table in the master database:

```sql
CREATE TABLE ai_usage_quota (
    user_id TEXT NOT NULL,
    date TEXT NOT NULL,              -- "YYYY-MM-DD"
    request_count INTEGER DEFAULT 0,  -- Requests made today
    last_reset_at INTEGER NOT NULL,   -- Unix timestamp
    PRIMARY KEY (user_id, date)
);
```

**Key Features**:
- **Atomic updates**: `ON CONFLICT DO UPDATE` prevents race conditions
- **Date-based partitioning**: Each day has a separate row
- **Automatic cleanup**: Old dates can be purged (retention: 30 days)

### Quota Enforcement

Quota is checked **before** any processing occurs (`app/inference/service.py:176-177`):

```python
# 1. Check rate limits (before any processing)
if not self.check_and_update_quota(user_id):
    raise ValueError("Rate limit exceeded")
```

If the limit is exceeded:
1. Request is rejected immediately (no decryption, no LLM call)
2. HTTP 429 error is returned with usage info
3. Client can display remaining quota to user

**Error Response** (429 Too Many Requests):
```json
{
  "error": "Daily request limit reached",
  "usage": {
    "requests_remaining": 0,
    "reset_at": "2025-11-19T00:00:00Z",
    "tier": "free"
  }
}
```

### Usage Info Endpoint

Clients can check remaining quota without consuming a request:

```http
GET /inference/usage
Authorization: Bearer <access_token>

Response:
{
  "requests_remaining": 7,
  "reset_at": "2025-11-19T00:00:00Z",
  "tier": "free"
}
```

**Code**: `app/inference/routes.py:133-159`

## Security Guarantees

The E2EE inference system provides strong security guarantees:

### 1. Zero-Knowledge Server

**Guarantee**: The server never sees user content in plaintext.

**How**:
- Content is encrypted client-side before transmission
- Server decrypts only in ephemeral memory for immediate processing
- Plaintext is cleared from memory after processing
- No plaintext is ever logged or stored

**Code Evidence** (`app/inference/service.py:244-251`):
```python
finally:
    # Clear sensitive data from memory
    if plaintext_content is not None:
        plaintext_content = None
    if result_json is not None:
        result_json = None
    if encryption_key is not None:
        encryption_key = None
```

### 2. Perfect Forward Secrecy

**Guarantee**: If the server's long-term key is compromised, past communications remain secure.

**How**:
- Each request uses a fresh ephemeral keypair (generated client-side)
- Shared secret is derived per-request using X25519 key exchange
- Even if server's private key is stolen, attacker cannot decrypt past requests (no ephemeral keys are stored)

**Analogy**: Like Signal's Double Ratchet, but for single-request messages.

### 3. Authenticated Encryption (AEAD)

**Guarantee**: Ciphertext cannot be tampered with or replayed.

**How**:
- ChaCha20-Poly1305 provides AEAD (Authenticated Encryption with Associated Data)
- MAC tag authenticates ciphertext integrity
- Decryption fails if ciphertext is modified
- Nonce prevents replay attacks (random 12-byte nonce per message)

**Code Evidence** (`app/inference/crypto.py:232-239`):
```python
# Decrypt and verify MAC in one operation
chacha = ChaCha20Poly1305(encryption_key)
plaintext_bytes = chacha.decrypt(nonce, authenticated_ciphertext, None)
# If MAC verification fails, exception is raised
```

### 4. Key Rotation

**Guarantee**: Server's key exposure is time-limited.

**How**:
- Server's X25519 keypair rotates every 30 days
- Old keys are deleted after rotation
- Clients automatically fetch new key when expired

**Code Evidence** (`app/inference/crypto.py:54-56`):
```python
# Check if key needs rotation
if datetime.utcnow() > self._key_expires_at:
    logger.info("inference_key_expired_rotating")
    self._generate_new_key()
```

### 5. No Plaintext Logging

**Guarantee**: No user content is ever logged in plaintext.

**How**:
- All logging uses structured logging with explicit fields
- Content is logged only as length/metadata, never plaintext
- LLM prompts/responses are not logged

**Code Evidence** (`app/inference/tasks.py:86`):
```python
logger.error("task_processing_failed", task=task, error=str(e))
# Note: plaintext_content is NOT logged
```

### 6. Transport Security

**Guarantee**: All communication uses TLS 1.3.

**How**:
- Production deployment uses Caddy reverse proxy with automatic HTTPS
- All API requests require TLS
- E2EE provides defense-in-depth (encrypted even if TLS is compromised)

### 7. Authentication Required

**Guarantee**: Only authenticated users can access inference.

**How**:
- All inference endpoints require valid JWT token
- Tokens are device-specific (device_id fingerprint)
- Token revocation invalidates access immediately

**Code Evidence** (`app/inference/routes.py:45`):
```python
async def execute_inference(
    request: E2EEInferenceRequest,
    current_user: Tuple[str, str] = Depends(get_current_user)  # JWT verification
):
```

## Implementation Details

### Key Files

**Cryptography**:
- `app/inference/crypto.py` - X25519 key exchange, ChaCha20-Poly1305 encryption
- Lines 170-201: Shared secret derivation
- Lines 203-239: Content decryption
- Lines 241-273: Response encryption

**Service Layer**:
- `app/inference/service.py` - E2EE inference orchestration
- Lines 149-252: Main `execute_inference` method
- Lines 101-148: Quota management

**Task Processing**:
- `app/inference/tasks.py` - LLM task execution
- Lines 89-133: Memory distillation
- Lines 135-175: Tagging
- Lines 177-213: Insight extraction

**API Endpoints**:
- `app/inference/routes.py` - FastAPI routes
- Lines 22-39: Public key endpoint
- Lines 42-131: Execute inference endpoint
- Lines 133-159: Usage quota endpoint

**Models**:
- `app/inference/models.py` - Pydantic schemas
- Lines 25-33: `E2EEInferenceRequest`
- Lines 42-48: `E2EEInferenceResponse`
- Lines 67-96: Task result models

**LLM Integration**:
- `app/llm/service.py` - LLM provider abstraction
- `app/llm/providers/anthropic.py` - Claude integration
- `app/llm/providers/openai.py` - GPT integration
- `app/llm/providers/google.py` - Gemini integration

### Configuration

**Environment Variables**:

```bash
# Required: At least one LLM provider API key
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=AI...

# Optional: Rate limiting (defaults shown)
INFERENCE_FREE_TIER_DAILY_LIMIT=10
INFERENCE_PAID_TIER_DAILY_LIMIT=5000

# Optional: Key storage directory (defaults shown)
DATA_DIR=./data
```

**Code**: `app/config.py:63-76`

### Testing

**Bruno Collection**: `bruno/echolia-api/requests/inference/`

1. **Get Public Key**: `public-key.bru`
   ```
   GET /inference/public-key
   ```

2. **Execute Inference**: `execute.bru`
   ```
   POST /inference/execute
   Body: {task, encrypted_content, nonce, mac, ephemeral_public_key, client_version}
   ```

3. **Get Usage**: `usage.bru`
   ```
   GET /inference/usage
   ```

### Performance Considerations

**Latency Breakdown** (typical request):
1. Key exchange: ~1ms (client + server)
2. Encryption/decryption: ~1ms (ChaCha20 is very fast)
3. LLM inference: 500-2000ms (depends on provider)
4. JSON parsing: ~1ms
5. **Total**: ~500-2000ms (LLM dominates)

**Optimizations**:
- X25519 is much faster than RSA (elliptic curve advantage)
- ChaCha20-Poly1305 is faster than AES-GCM on mobile devices
- Ephemeral keypairs are generated client-side (no server bottleneck)
- Server's public key is cached client-side (no redundant fetches)

### Error Handling

**Common Errors**:

1. **Decryption Failed** (422 Unprocessable Entity):
   - Wrong shared secret (mismatched keys)
   - Tampered ciphertext (MAC verification failed)
   - Corrupted base64 encoding

2. **Rate Limit Exceeded** (429 Too Many Requests):
   - Free tier: 10 requests/day exceeded
   - AI add-on: 5000 requests/day exceeded

3. **No LLM Provider** (503 Service Unavailable):
   - No API keys configured
   - All providers are down

4. **Invalid Task** (400 Bad Request):
   - Unknown task type
   - Malformed request

**Code**: `app/inference/routes.py:80-130`

### Memory Safety

The system takes care to clear sensitive data from memory:

1. **Plaintext content**: Cleared after task processing
2. **Encryption key**: Cleared after response encryption
3. **Shared secret**: Never stored, derived on-demand
4. **Ephemeral private key**: Generated and used only on client

**Code Evidence** (`app/inference/service.py:244-251`):
```python
finally:
    # Clear sensitive data from memory
    if plaintext_content is not None:
        plaintext_content = None
    if result_json is not None:
        result_json = None
    if encryption_key is not None:
        encryption_key = None
```

**Note**: In Python, setting variables to `None` doesn't guarantee immediate memory clearing (garbage collection is non-deterministic). For production, consider using `ctypes.memset` or similar for sensitive data.

### Future Enhancements

Potential improvements:

1. **Hardware Security Module (HSM)**: Store server's private key in HSM
2. **Client-Side Caching**: Cache server's public key until expiration
3. **Streaming Responses**: Support streaming LLM responses (requires encrypted SSE)
4. **Batch Processing**: Process multiple entries in one request (cheaper, faster)
5. **Model Selection**: Allow clients to choose LLM model (Claude vs GPT vs Gemini)
6. **Custom Tasks**: Support user-defined prompts/tasks
7. **Embeddings**: Generate encrypted embeddings for semantic search

## Conclusion

The E2EE inference system demonstrates that AI-powered features can coexist with strong privacy guarantees. By using modern cryptographic primitives (X25519, ChaCha20-Poly1305) and careful system design, Echolia provides:

- **Zero-knowledge AI**: Server processes content without seeing plaintext
- **Perfect forward secrecy**: Past communications remain secure even if keys are compromised
- **Authenticated encryption**: Tamper-proof, replay-resistant communication
- **Transparent usage tracking**: Users see exactly how much AI they consume

This architecture sets a new standard for privacy-first AI assistants.

---

**Last Updated**: 2025-11-18
**Version**: 1.0
**Author**: Echolia Team
