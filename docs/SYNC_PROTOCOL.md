# Echolia Sync Protocol

This document describes the sync protocol for Echolia mobile (Flutter) and desktop (Tauri) apps.

## Overview

The Echolia sync service enables encrypted data synchronization across multiple devices using:

- **Vector clocks** for conflict detection in journal entries
- **Timestamp-based sync** for memories and tags (last-write-wins)
- **Soft deletes** (tombstones) for proper deletion propagation
- **Zero-knowledge encryption** (all data encrypted client-side)

## Prerequisites

- Sync add-on must be active (subscription required)
- User must be authenticated with valid access token
- Device must be registered in the system

## API Endpoints

### Base URL

```
https://api.echolia.app
```

For local development:
```
http://localhost:8000
```

### Authentication

All sync endpoints require a valid JWT access token in the `Authorization` header:

```http
Authorization: Bearer <access_token>
```

### Endpoints

1. **GET /sync/status** - Get sync status
2. **POST /sync/push** - Push local changes to server
3. **POST /sync/pull** - Pull changes from server

---

## 1. Get Sync Status

Check sync status before starting sync operation.

### Request

```http
GET /sync/status
Authorization: Bearer <access_token>
```

### Response

```json
{
  "user_id": "user-uuid",
  "total_entries": 150,
  "total_memories": 45,
  "total_tags": 89,
  "last_sync_at": 1704153600,
  "device_count": 3,
  "sync_enabled": true
}
```

### Fields

- `user_id`: User's UUID
- `total_entries`: Total entries on server (excluding deleted)
- `total_memories`: Total memories on server (excluding deleted)
- `total_tags`: Total tags on server (excluding deleted)
- `last_sync_at`: Unix timestamp of last sync operation (null if never synced)
- `device_count`: Number of registered devices
- `sync_enabled`: Whether sync add-on is active

### Usage

```dart
// Flutter example
Future<SyncStatus> getSyncStatus() async {
  final response = await http.get(
    Uri.parse('$baseUrl/sync/status'),
    headers: {'Authorization': 'Bearer $accessToken'},
  );

  if (response.statusCode == 200) {
    return SyncStatus.fromJson(jsonDecode(response.body));
  } else {
    throw Exception('Failed to get sync status');
  }
}
```

---

## 2. Push Changes to Server

Push local changes to server. Returns conflicts that need resolution.

### Request

```http
POST /sync/push
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "entries": [
    {
      "id": "entry-123",
      "device_id": "device-abc",
      "encrypted_data": "<base64_encoded_encrypted_blob>",
      "version": 5,
      "vector_clock": {
        "device-abc": 5,
        "device-xyz": 3
      },
      "is_deleted": false,
      "created_at": 1704067200,
      "updated_at": 1704153600
    }
  ],
  "memories": [
    {
      "id": "memory-456",
      "encrypted_data": "<base64_encoded_encrypted_blob>",
      "version": 2,
      "is_deleted": false,
      "created_at": 1704067200,
      "updated_at": 1704153600
    }
  ],
  "tags": [
    {
      "id": "tag-789",
      "entry_id": "entry-123",
      "encrypted_data": "<base64_encoded_encrypted_blob>",
      "version": 1,
      "is_deleted": false,
      "created_at": 1704067200,
      "updated_at": 1704153600
    }
  ],
  "last_sync_at": 1704067200
}
```

### Response

```json
{
  "accepted_entries": 5,
  "accepted_memories": 2,
  "accepted_tags": 3,
  "conflicts": [
    {
      "item_type": "entry",
      "item_id": "entry-123",
      "server_version": {
        "encrypted_data": "<base64_server_version>",
        "version": 6,
        "vector_clock": {"device-xyz": 6},
        "is_deleted": false,
        "created_at": 1704067200,
        "updated_at": 1704160000
      },
      "client_version": {
        "encrypted_data": "<base64_client_version>",
        "version": 5,
        "vector_clock": {"device-abc": 5},
        "is_deleted": false,
        "created_at": 1704067200,
        "updated_at": 1704153600
      },
      "conflict_reason": "concurrent_modification"
    }
  ],
  "server_time": 1704153600
}
```

### Fields

**Request:**
- `entries`: List of encrypted journal entries
- `memories`: List of encrypted memories (knowledge graph nodes)
- `tags`: List of encrypted tags
- `last_sync_at`: Client's last known sync timestamp (optional)

**Entry Object:**
- `id`: Unique entry ID (UUID)
- `device_id`: Device that created/last modified the entry
- `encrypted_data`: Base64-encoded encrypted BLOB
- `version`: Entry version number (increment on each edit)
- `vector_clock`: Map of device_id ’ version for conflict detection
- `is_deleted`: Soft delete flag (true = deleted, false = active)
- `created_at`: Unix timestamp of creation
- `updated_at`: Unix timestamp of last update

**Memory Object:**
- `id`: Unique memory ID (UUID)
- `encrypted_data`: Base64-encoded encrypted BLOB
- `version`: Memory version number
- `is_deleted`: Soft delete flag
- `created_at`: Unix timestamp of creation
- `updated_at`: Unix timestamp of last update

**Tag Object:**
- `id`: Unique tag ID (UUID)
- `entry_id`: ID of associated entry
- `encrypted_data`: Base64-encoded encrypted BLOB
- `version`: Tag version number
- `is_deleted`: Soft delete flag
- `created_at`: Unix timestamp of creation
- `updated_at`: Unix timestamp of last update

**Response:**
- `accepted_entries`: Number of entries accepted by server
- `accepted_memories`: Number of memories accepted by server
- `accepted_tags`: Number of tags accepted by server
- `conflicts`: List of conflicts detected (client should resolve)
- `server_time`: Server's current Unix timestamp

**Conflict Object:**
- `item_type`: Type of item in conflict ("entry", "memory", "tag")
- `item_id`: ID of conflicting item
- `server_version`: Server's version of the item
- `client_version`: Client's version (from push request)
- `conflict_reason`: Reason for conflict ("concurrent_modification", "server_version_newer")

### Usage

```dart
// Flutter example
Future<PushResponse> pushChanges(List<Entry> entries, List<Memory> memories, List<Tag> tags) async {
  final request = {
    'entries': entries.map((e) => e.toJson()).toList(),
    'memories': memories.map((m) => m.toJson()).toList(),
    'tags': tags.map((t) => t.toJson()).toList(),
    'last_sync_at': lastSyncTimestamp,
  };

  final response = await http.post(
    Uri.parse('$baseUrl/sync/push'),
    headers: {
      'Authorization': 'Bearer $accessToken',
      'Content-Type': 'application/json',
    },
    body: jsonEncode(request),
  );

  if (response.statusCode == 200) {
    return PushResponse.fromJson(jsonDecode(response.body));
  } else if (response.statusCode == 403) {
    throw Exception('Sync add-on required');
  } else {
    throw Exception('Push failed: ${response.body}');
  }
}
```

---

## 3. Pull Changes from Server

Pull all changes from server since last sync.

### Request

```http
POST /sync/pull
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "last_sync_at": 1704067200,
  "device_id": "device-abc"
}
```

### Response

```json
{
  "entries": [
    {
      "id": "entry-456",
      "device_id": "device-xyz",
      "encrypted_data": "<base64_encoded_encrypted_blob>",
      "version": 3,
      "vector_clock": {
        "device-xyz": 3
      },
      "is_deleted": false,
      "created_at": 1704067200,
      "updated_at": 1704153600
    }
  ],
  "memories": [],
  "tags": [],
  "server_time": 1704153600,
  "has_more": false
}
```

### Fields

**Request:**
- `last_sync_at`: Unix timestamp of last successful sync
- `device_id`: Current device ID (for vector clock filtering)

**Response:**
- `entries`: List of entries updated since last_sync_at
- `memories`: List of memories updated since last_sync_at
- `tags`: List of tags updated since last_sync_at
- `server_time`: Server's current Unix timestamp (use this as new last_sync_at)
- `has_more`: Pagination flag (future use, currently always false)

### Usage

```dart
// Flutter example
Future<PullResponse> pullChanges(int lastSyncAt, String deviceId) async {
  final request = {
    'last_sync_at': lastSyncAt,
    'device_id': deviceId,
  };

  final response = await http.post(
    Uri.parse('$baseUrl/sync/pull'),
    headers: {
      'Authorization': 'Bearer $accessToken',
      'Content-Type': 'application/json',
    },
    body: jsonEncode(request),
  );

  if (response.statusCode == 200) {
    return PullResponse.fromJson(jsonDecode(response.body));
  } else if (response.statusCode == 403) {
    throw Exception('Sync add-on required');
  } else {
    throw Exception('Pull failed: ${response.body}');
  }
}
```

---

## Sync Protocol Flow

### Initial Sync (First Time)

```
1. User enables sync add-on
2. App checks sync status (GET /sync/status)
3. If last_sync_at is null:
   a. Push all local data (POST /sync/push)
   b. Pull all remote data (POST /sync/pull with last_sync_at = 0)
   c. Merge data locally
   d. Store server_time as last_sync_at
```

### Incremental Sync (Subsequent Syncs)

```
1. App starts sync operation
2. Pull changes first (POST /sync/pull with last_sync_at)
3. Merge pulled changes into local database
4. Update vector clocks for entries
5. Push local changes (POST /sync/push)
6. If conflicts detected:
   a. Resolve conflicts (see Conflict Resolution below)
   b. Re-push resolved items
7. Store server_time as new last_sync_at
```

### Recommended Sync Triggers

- On app foreground (after 5+ minutes in background)
- After significant local changes (batch of 10+ edits)
- Periodic background sync (every 15-30 minutes if app active)
- Manual sync button in settings
- Before/after device switch

---

## Vector Clocks for Entries

Vector clocks enable conflict detection for journal entries across multiple devices.

### Structure

A vector clock is a JSON object mapping device IDs to version numbers:

```json
{
  "device-abc": 5,
  "device-xyz": 3,
  "device-123": 1
}
```

### Rules

1. **On Local Edit:**
   - Increment the version for your device_id
   - Example: `{"device-abc": 5}` ’ `{"device-abc": 6}`

2. **On Receiving Remote Changes:**
   - Merge vector clocks by taking the max for each device
   - Example:
     - Local: `{"device-abc": 5, "device-xyz": 2}`
     - Remote: `{"device-abc": 4, "device-xyz": 3}`
     - Merged: `{"device-abc": 5, "device-xyz": 3}`

3. **On Creating New Entry:**
   - Initialize with your device_id ’ version 1
   - Example: `{"device-abc": 1}`

### Conflict Detection

The server compares vector clocks to detect conflicts:

- **Greater**: Remote version happened after local ’ Accept remote
- **Less**: Local version happened after remote ’ Accept local
- **Equal**: Same version ’ No update needed
- **Concurrent**: Neither is greater ’ **CONFLICT!**

**Concurrent Example:**
- Device A: `{"device-a": 5, "device-b": 2}` (edited on device A)
- Device B: `{"device-a": 3, "device-b": 4}` (edited on device B)
- Result: Concurrent modification detected

### Implementation

```dart
// Flutter example
class VectorClock {
  Map<String, int> clock;

  VectorClock(this.clock);

  // Increment version for current device
  void increment(String deviceId) {
    clock[deviceId] = (clock[deviceId] ?? 0) + 1;
  }

  // Merge with another vector clock (take max)
  void merge(VectorClock other) {
    other.clock.forEach((deviceId, version) {
      clock[deviceId] = max(clock[deviceId] ?? 0, version);
    });
  }

  // Compare with another vector clock
  ClockComparison compare(VectorClock other) {
    bool thisGreater = false;
    bool otherGreater = false;

    final allDevices = {...clock.keys, ...other.clock.keys};

    for (final deviceId in allDevices) {
      final thisVersion = clock[deviceId] ?? 0;
      final otherVersion = other.clock[deviceId] ?? 0;

      if (thisVersion > otherVersion) thisGreater = true;
      if (thisVersion < otherVersion) otherGreater = true;
    }

    if (thisGreater && !otherGreater) return ClockComparison.greater;
    if (otherGreater && !thisGreater) return ClockComparison.less;
    if (!thisGreater && !otherGreater) return ClockComparison.equal;
    return ClockComparison.concurrent;
  }

  Map<String, dynamic> toJson() => clock;
  factory VectorClock.fromJson(Map<String, dynamic> json) {
    return VectorClock(Map<String, int>.from(json));
  }
}

enum ClockComparison { greater, less, equal, concurrent }
```

---

## Conflict Resolution

### Entry Conflicts (Vector Clock-Based)

When a conflict is detected for an entry:

1. **Automatic Resolution (Server-side):**
   - Server uses timestamp as tiebreaker (last-write-wins)
   - Merges vector clocks automatically
   - Returns conflict details to client

2. **Client-side Handling:**
   ```dart
   void handleConflicts(List<Conflict> conflicts) {
     for (final conflict in conflicts) {
       if (conflict.itemType == 'entry') {
         // Option 1: Accept server version
         acceptServerVersion(conflict);

         // Option 2: Keep local version and re-push
         rejectServerVersion(conflict);

         // Option 3: Manual merge (decrypt, merge content, re-encrypt)
         manualMerge(conflict);
       }
     }
   }
   ```

3. **Recommended Strategy:**
   - For auto-save entries: Accept server version (user likely edited on another device)
   - For explicit user edits: Show conflict UI and let user choose
   - For programmatic changes: Merge content intelligently

### Memory/Tag Conflicts (Timestamp-Based)

Memories and tags use simple last-write-wins:

- Server compares `updated_at` timestamps
- Higher timestamp wins automatically
- No manual conflict resolution needed

### Conflict Prevention

To minimize conflicts:

1. **Sync frequently** (before/after edits)
2. **Use optimistic locking** (check last_sync_at before editing)
3. **Increment vector clocks properly**
4. **Handle offline edits gracefully**

---

## Soft Deletes (Tombstones)

Echolia uses soft deletes to properly propagate deletions across devices.

### How It Works

1. **Local Deletion:**
   - Set `is_deleted = true`
   - Update `updated_at` timestamp
   - Increment version/vector clock
   - Keep item in local database (don't hard delete)

2. **Push Deletion:**
   - Push deleted item with `is_deleted = true`
   - Server stores tombstone

3. **Pull Deletion:**
   - Receive deleted item from server
   - Mark local copy as deleted
   - Hide from UI but keep in database

4. **Garbage Collection:**
   - After 30+ days, permanently delete tombstones
   - Run cleanup task periodically

### Implementation

```dart
// Mark item as deleted (don't hard delete)
Future<void> deleteEntry(String entryId) async {
  final entry = await getEntry(entryId);
  entry.isDeleted = true;
  entry.updatedAt = DateTime.now().millisecondsSinceEpoch ~/ 1000;
  entry.vectorClock.increment(currentDeviceId);

  await saveEntry(entry);
  await syncManager.push([entry], [], []);
}

// Filter out deleted items in queries
Future<List<Entry>> getActiveEntries() async {
  return await db.query(
    'entries',
    where: 'is_deleted = ?',
    whereArgs: [0],
  );
}

// Garbage collection (run periodically)
Future<void> cleanupTombstones() async {
  final cutoff = DateTime.now().subtract(Duration(days: 30));
  await db.delete(
    'entries',
    where: 'is_deleted = ? AND updated_at < ?',
    whereArgs: [1, cutoff.millisecondsSinceEpoch ~/ 1000],
  );
}
```

---

## Data Encryption

All user data is encrypted client-side before syncing (zero-knowledge).

### Encryption Flow

```
1. User creates/edits entry locally
2. Serialize data to JSON
3. Encrypt JSON with user's encryption key
4. Base64-encode encrypted blob
5. Store in encrypted_data field
6. Push to server (server never sees plaintext)
```

### Decryption Flow

```
1. Pull encrypted data from server
2. Base64-decode encrypted blob
3. Decrypt blob with user's encryption key
4. Deserialize JSON to object
5. Display in app
```

### Security Notes

- **Never send encryption keys to server**
- **Derive encryption key from user's OAuth identity** (deterministic)
- **Use AES-256-GCM for encryption**
- **Generate unique nonce for each encryption**
- **Store nonce with encrypted data** (prepend to blob)

### Example Implementation

```dart
import 'dart:convert';
import 'dart:typed_data';
import 'package:cryptography/cryptography.dart';

class EncryptionService {
  final SecretKey _key;
  final AesGcm _algorithm = AesGcm.with256bits();

  EncryptionService(this._key);

  // Encrypt data
  Future<String> encrypt(Map<String, dynamic> data) async {
    final plaintext = utf8.encode(jsonEncode(data));
    final secretBox = await _algorithm.encrypt(
      plaintext,
      secretKey: _key,
    );

    // Combine nonce + ciphertext + mac
    final combined = Uint8List.fromList([
      ...secretBox.nonce,
      ...secretBox.cipherText,
      ...secretBox.mac.bytes,
    ]);

    return base64Encode(combined);
  }

  // Decrypt data
  Future<Map<String, dynamic>> decrypt(String encryptedData) async {
    final combined = base64Decode(encryptedData);

    // Split nonce + ciphertext + mac
    final nonce = combined.sublist(0, 12);
    final cipherText = combined.sublist(12, combined.length - 16);
    final macBytes = combined.sublist(combined.length - 16);

    final secretBox = SecretBox(
      cipherText,
      nonce: nonce,
      mac: Mac(macBytes),
    );

    final plaintext = await _algorithm.decrypt(
      secretBox,
      secretKey: _key,
    );

    return jsonDecode(utf8.decode(plaintext));
  }
}
```

---

## Error Handling

### HTTP Status Codes

- **200 OK**: Request successful
- **400 Bad Request**: Invalid request format
- **401 Unauthorized**: Invalid or expired access token
- **403 Forbidden**: Sync add-on not active
- **500 Internal Server Error**: Server-side error

### Common Errors

1. **Sync Add-on Required (403)**
   ```json
   {
     "detail": "Sync add-on required. Please subscribe to enable cross-device sync."
   }
   ```
   **Solution**: Prompt user to purchase sync add-on

2. **Unauthorized (401)**
   ```json
   {
     "detail": "Could not validate credentials"
   }
   ```
   **Solution**: Refresh access token or re-authenticate

3. **Large Payload (413)**
   - Server rejects payloads > 50MB
   - **Solution**: Batch sync in smaller chunks (max 1000 items per request)

### Retry Logic

```dart
Future<T> retryWithBackoff<T>(
  Future<T> Function() operation, {
  int maxRetries = 3,
  Duration initialDelay = const Duration(seconds: 1),
}) async {
  int retries = 0;
  Duration delay = initialDelay;

  while (true) {
    try {
      return await operation();
    } catch (e) {
      if (retries >= maxRetries) rethrow;

      await Future.delayed(delay);
      retries++;
      delay *= 2; // Exponential backoff
    }
  }
}
```

---

## Performance Optimization

### Batching

Push/pull changes in batches to reduce network overhead:

```dart
// Batch push
Future<void> syncAll() async {
  final pendingEntries = await getPendingEntries();
  final pendingMemories = await getPendingMemories();
  final pendingTags = await getPendingTags();

  // Push in chunks of 1000
  for (int i = 0; i < pendingEntries.length; i += 1000) {
    final batch = pendingEntries.sublist(
      i,
      min(i + 1000, pendingEntries.length),
    );
    await pushChanges(batch, [], []);
  }
}
```

### Incremental Sync

Only sync items that changed since last sync:

```dart
// Track local changes
Future<List<Entry>> getChangedEntries(int lastSyncAt) async {
  return await db.query(
    'entries',
    where: 'updated_at > ?',
    whereArgs: [lastSyncAt],
  );
}
```

### Delta Sync

For large entries, consider delta sync (future enhancement):
- Only send changed fields instead of full entry
- Requires CRDT or operational transformation
- Not currently supported (future roadmap)

---

## Testing

### Test Scenarios

1. **Single Device Sync**
   - Create entry on device A
   - Push to server
   - Verify entry stored correctly

2. **Multi-Device Sync**
   - Create entry on device A, push
   - Pull on device B
   - Verify entry appears on device B

3. **Concurrent Edits**
   - Edit entry on device A (offline)
   - Edit same entry on device B (offline)
   - Push from both devices
   - Verify conflict detected and resolved

4. **Soft Deletes**
   - Delete entry on device A
   - Push deletion
   - Pull on device B
   - Verify entry marked deleted (not hard deleted)

5. **Large Payload**
   - Create 5000 entries
   - Push in batches
   - Verify all entries synced

### Test Tools

Use Bruno collection for API testing:

```
POST http://localhost:8000/sync/push
Authorization: Bearer <test_token>
Content-Type: application/json

{
  "entries": [...],
  "memories": [],
  "tags": []
}
```

---

## Limits and Quotas

- **Max payload size**: 50 MB per request
- **Max items per sync**: 1000 items (entries + memories + tags)
- **Max syncs per hour**: 100 (rate limit)
- **Tombstone retention**: 30 days

---

## Future Enhancements

1. **Delta Sync**: Only sync changed fields (reduce bandwidth)
2. **Selective Sync**: Sync only specific entries (favorites, recent)
3. **Pagination**: Support for large datasets (has_more flag)
4. **Conflict UI**: Built-in conflict resolution UI
5. **Compression**: Gzip compression for encrypted payloads
6. **WebSocket Sync**: Real-time sync via WebSockets

---

## Support

For questions or issues:

- GitHub: https://github.com/osmanorhan/echolia-backend
- Email: support@echolia.app
- Docs: https://docs.echolia.app

---

## Changelog

### v1.0.0 (2024-11-18)
- Initial sync protocol implementation
- Vector clock conflict detection for entries
- Timestamp-based sync for memories/tags
- Soft deletes (tombstones)
- Sync add-on enforcement
