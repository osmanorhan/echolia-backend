#!/usr/bin/env bash
set -euo pipefail

# Run master DB migrations (creates DB if missing, ensures schema).

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

REQUIRED_VARS=(TURSO_ORG_URL TURSO_AUTH_TOKEN)
missing=()
for var in "${REQUIRED_VARS[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    missing+=("$var")
  fi
done

if (( ${#missing[@]} > 0 )); then
  echo "Missing required environment variables: ${missing[*]}" >&2
  exit 1
fi

# Avoid permission issues with default uv cache on some systems.
export UV_CACHE_DIR="${UV_CACHE_DIR:-$ROOT/.uvcache}"

RUNNER=("python" "-")
if command -v uv >/dev/null 2>&1; then
  RUNNER=("uv" "run" "python" "-")
fi

"${RUNNER[@]}" <<'PY'
import asyncio
from app.master_db import master_db_manager

async def main():
    await master_db_manager.create_master_database()
    master_db_manager._ensure_schema()
    print("Master database ensured (exists + schema applied).")

asyncio.run(main())
PY
