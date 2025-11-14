# Echolia Backend - API Reference

Base URL: `http://localhost:8000` (development)
Production: `https://api.echolia.app` (when deployed)

All timestamps are Unix timestamps (seconds since epoch).

---

## Authentication

All authenticated endpoints require a Bearer token in the Authorization header:

```
Authorization: Bearer {access_token}
```

---

## Endpoints

### Health & Status

#### GET /
Get service information.

**Response:**
```json
{
  "service": "Echolia Backend",
  "version": "0.1.0",
  "status": "operational",
  "environment": "development"
}
```

#### GET /health
Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "database": "connected"
}
```

---

### Authentication

#### POST /auth/register
Register a new anonymous user with their first device.

**Request:**
```json
{
  "device_name": "My MacBook Pro",
  "device_type": "desktop",  // "desktop" or "mobile"
  "platform": "macos",       // macos, windows, linux, ios, android
  "public_key": "-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA...\n-----END PUBLIC KEY-----"
}
```

**Response:** `200 OK`
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "device_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**Errors:**
- `400 Bad Request` - Invalid public key or request data
- `500 Internal Server Error` - Database creation failed

**Notes:**
- No email or password required
- Store `user_id`, `device_id`, and tokens securely on device
- Public key must be PEM-encoded RSA public key
- Creates user's personal database automatically

---

#### POST /auth/pair-device
Pair a new device to an existing account.

**Headers:**
```
Authorization: Bearer {access_token}
```

**Request:**
```json
{
  "device_name": "My iPhone",
  "device_type": "mobile",
  "platform": "ios",
  "public_key": "-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----"
}
```

**Response:** `200 OK`
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

**Errors:**
- `401 Unauthorized` - Invalid or expired token
- `400 Bad Request` - Invalid public key
- `500 Internal Server Error` - Pairing failed

**Notes:**
- Requires authentication from an existing device
- New device gets its own access/refresh tokens
- Enables multi-device sync

---

#### GET /auth/devices
List all devices paired to the account.

**Headers:**
```
Authorization: Bearer {access_token}
```

**Response:** `200 OK`
```json
[
  {
    "device_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
    "device_name": "My MacBook Pro",
    "device_type": "desktop",
    "platform": "macos",
    "public_key": "-----BEGIN PUBLIC KEY-----\n...",
    "last_sync_at": 1699564800,
    "created_at": 1699478400
  },
  {
    "device_id": "7ca8c910-adbe-22e2-91c5-11d15fe540d9",
    "device_name": "My iPhone",
    "device_type": "mobile",
    "platform": "ios",
    "public_key": "-----BEGIN PUBLIC KEY-----\n...",
    "last_sync_at": 1699564900,
    "created_at": 1699564800
  }
]
```

**Errors:**
- `401 Unauthorized` - Invalid or expired token
- `500 Internal Server Error` - Database query failed

---

#### DELETE /auth/device/{device_id}
Revoke access for a specific device.

**Headers:**
```
Authorization: Bearer {access_token}
```

**Parameters:**
- `device_id` (path) - UUID of device to revoke

**Response:** `200 OK`
```json
{
  "message": "Device revoked successfully"
}
```

**Errors:**
- `401 Unauthorized` - Invalid or expired token
- `400 Bad Request` - Cannot revoke current device
- `404 Not Found` - Device not found
- `500 Internal Server Error` - Revocation failed

**Notes:**
- Cannot revoke the device you're currently using
- Revoked device's tokens become invalid immediately
- Use to remove lost or stolen devices

---

#### POST /auth/refresh
Refresh access token using refresh token.

**Request:**
```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Response:** `200 OK`
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

**Errors:**
- `401 Unauthorized` - Invalid or expired refresh token

**Notes:**
- Access tokens expire after 1 hour
- Refresh tokens expire after 30 days
- Both tokens are rotated on refresh

---

## Data Models

### Device Info
```typescript
{
  device_id: string;          // UUID
  device_name?: string;       // Optional friendly name
  device_type: "desktop" | "mobile";
  platform: string;           // macos, windows, linux, ios, android
  public_key: string;         // PEM-encoded RSA public key
  last_sync_at?: number;      // Unix timestamp
  created_at: number;         // Unix timestamp
}
```

### Token Response
```typescript
{
  access_token: string;       // JWT access token (1 hour)
  refresh_token: string;      // JWT refresh token (30 days)
  token_type: "bearer";       // Always "bearer"
  expires_in?: number;        // Seconds until expiration
}
```

---

## Error Responses

All error responses follow this format:

```json
{
  "detail": "Error message description"
}
```

### HTTP Status Codes
- `200 OK` - Request succeeded
- `400 Bad Request` - Invalid request data
- `401 Unauthorized` - Authentication required or failed
- `404 Not Found` - Resource not found
- `500 Internal Server Error` - Server error

---

## Rate Limiting

Current limits (configurable):
- 100 requests per minute per IP
- 20 burst requests

**Rate limit headers:**
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1699564800
```

When rate limited, returns `429 Too Many Requests`.

---

## Client Integration Example

### Registration Flow (Desktop)

```typescript
// 1. Generate keypair on device
const { publicKey, privateKey } = await generateKeyPair();

// 2. Register user
const response = await fetch('http://localhost:8000/auth/register', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    device_name: 'My MacBook Pro',
    device_type: 'desktop',
    platform: 'macos',
    public_key: publicKey
  })
});

const { user_id, device_id, access_token, refresh_token } = await response.json();

// 3. Store credentials securely
await secureStorage.set('user_id', user_id);
await secureStorage.set('device_id', device_id);
await secureStorage.set('access_token', access_token);
await secureStorage.set('refresh_token', refresh_token);
await secureStorage.set('private_key', privateKey);
```

### Pairing Flow (Mobile)

```typescript
// 1. Generate keypair on new device
const { publicKey, privateKey } = await generateKeyPair();

// 2. Get access token from existing device (via QR code or deep link)
const existingAccessToken = await getFromExistingDevice();

// 3. Pair new device
const response = await fetch('http://localhost:8000/auth/pair-device', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${existingAccessToken}`
  },
  body: JSON.stringify({
    device_name: 'My iPhone',
    device_type: 'mobile',
    platform: 'ios',
    public_key: publicKey
  })
});

const { access_token, refresh_token } = await response.json();

// 4. Store credentials on new device
await secureStorage.set('access_token', access_token);
await secureStorage.set('refresh_token', refresh_token);
await secureStorage.set('private_key', privateKey);
```

### Token Refresh Flow

```typescript
async function refreshAccessToken() {
  const refreshToken = await secureStorage.get('refresh_token');

  const response = await fetch('http://localhost:8000/auth/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken })
  });

  if (response.ok) {
    const { access_token, refresh_token } = await response.json();
    await secureStorage.set('access_token', access_token);
    await secureStorage.set('refresh_token', refresh_token);
    return access_token;
  } else {
    // Refresh token expired, need to re-authenticate
    await logout();
    throw new Error('Session expired');
  }
}
```

---

## Security Considerations

### Key Management
- Private keys NEVER leave the device
- Store private keys in platform keychain (Keychain on macOS/iOS, Keystore on Android)
- Public keys can be stored in plain text

### Token Storage
- Store tokens in secure storage (not localStorage/SharedPreferences)
- Use platform-specific secure storage APIs
- Clear tokens on logout

### Request Security
- Always use HTTPS in production
- Validate server SSL certificate
- Include CSRF protection for web clients

### E2EE Implementation
- Encrypt all sync data before upload
- Use AES-256-GCM for symmetric encryption
- Use RSA-OAEP for key exchange
- Verify signatures when receiving data from other devices

---

## Coming Soon

### Sync Endpoints (Phase 2)
- `POST /sync/push` - Upload encrypted entries
- `POST /sync/pull` - Download encrypted entries
- `GET /sync/status` - Get sync status

### LLM Endpoints (Phase 3)
- `POST /llm/generate` - Generate completion
- `POST /llm/stream` - Streaming completion
- `GET /llm/quota` - Check usage quota

### Payment Endpoints (Phase 4)
- `POST /payments/verify-receipt` - Verify App Store/Play Store receipt
- `GET /payments/subscription` - Get subscription status

---

Last Updated: 2025-11-13
Version: 0.1.0 (Phase 1 - Authentication Only)
