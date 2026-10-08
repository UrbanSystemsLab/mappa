#!/usr/bin/env bash
# Run Mappa on this laptop to check a change before it is released.
# Open http://127.0.0.1:8765 when it says it is ready.
#
#   ./scripts/run_local.sh              against the staging database (default)
#   ./scripts/run_local.sh production   against the live database, read-only use
#
# Staging is the default so that trying things locally can never change the
# live data.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! nc -z 127.0.0.1 5432 2>/dev/null; then
  echo "The Cloud SQL proxy is not running on port 5432. Start it first:"
  echo "  cloud-sql-proxy mappa-lamarana-aecc:us-central1:mappa-pg --port 5432"
  exit 1
fi
if [ ! -f .mappa_db_pw ]; then
  echo "Missing .mappa_db_pw (the database password file) in the repo folder."
  exit 1
fi
if lsof -nP -iTCP:8765 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Something is already running on port 8765 - an earlier copy of the app."
  echo "Stop it (Ctrl+C in its window, or: pkill -f 'uvicorn api.main:app --port 8765') and run this again."
  exit 1
fi

DB=mappa_staging
[ "${1:-}" = production ] && DB=mappa
export DATABASE_URL="postgresql://mappa:$(cat .mappa_db_pw)@127.0.0.1:5432/$DB"
export APP_ENV=local
# Local testing runs whole question sets; the public rate limit would block them.
export RATE_LIMIT_PER_MINUTE=600 RATE_LIMIT_PER_HOUR=20000
echo "Starting Mappa at http://127.0.0.1:8765 on database $DB (Ctrl+C to stop) ..."
exec ./venv/bin/uvicorn api.main:app --port 8765
