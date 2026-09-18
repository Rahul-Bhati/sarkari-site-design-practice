#!/usr/bin/env bash
#
# Fill the database with real notifications and nothing else.
#
#   ./scripts/real-data.sh            scrape every active source, then summarise
#   ./scripts/real-data.sh --purge    delete the seed rows first
#   ./scripts/real-data.sh --source gem
#
# The seed data in supabase/seed.sql exists so the UI has something to render
# before a scraper has ever run. It is invented — the URLs do not resolve. Use
# --purge once you want to look at the real thing.
#
# Summarising is deliberately slow: Groq's free tier caps tokens per minute, so
# the API processes 10 entries per call and this loops until none are pending.

set -euo pipefail

cd "$(dirname "$0")/.."

API="${API_BASE_URL:-http://localhost:8000}"
PURGE=false
SOURCE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --purge)  PURGE=true; shift ;;
    --source) SOURCE="$2"; shift 2 ;;
    -h|--help) sed -n '2,14p' "$0" | sed 's/^# \?//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ ! -f backend/.env ]]; then
  echo "backend/.env is missing. Copy backend/.env.example and fill it in." >&2
  exit 1
fi

# Read the admin key through pydantic so .env parsing matches the app's.
#
# _env_file is passed explicitly because Settings declares env_file=".env",
# which resolves against the *current directory*. This script runs from the
# repo root, so the plain Settings() read every value as empty and reported a
# missing ADMIN_API_KEY on a correctly configured machine.
ADMIN_KEY="$(backend/.venv/bin/python -c \
  'import sys; sys.path.insert(0, "backend"); from app.config import Settings; print(Settings(_env_file="backend/.env").admin_api_key or "")')"

if [[ -z "$ADMIN_KEY" ]]; then
  echo "ADMIN_API_KEY is not set in backend/.env." >&2
  exit 1
fi

if ! curl -sf -o /dev/null "$API/health"; then
  echo "No API at $API — start it with:" >&2
  echo "  cd backend && .venv/bin/uvicorn app.main:app --port 8000 --reload" >&2
  exit 1
fi

api() { curl -s -X "$1" "$API$2" -H "X-Admin-Key: $ADMIN_KEY" --max-time "${3:-300}"; }

if $PURGE; then
  echo "==> Deleting seed entries"
  # Run from backend/, not the repo root: app.config declares env_file=".env",
  # which pydantic resolves against the current directory, so importing
  # app.database from anywhere else silently sees no configuration at all.
  (cd backend && .venv/bin/python - <<'PY'
from app.database import db

# Every seed row carries content_hash='seed_hash_NNNN', which a real scraper can
# never produce — a real hash is 64 hex characters from sha256.
#
# This used to match invented URL substrings instead, and that was quietly
# wrong twice over: it caught only 3 of the 19 seed rows, and it could not have
# caught the rest safely anyway. The fabricated PIB entries use
# `pib.gov.in/PressReleasePage.aspx?PRID=...`, which is exactly the shape of a
# genuine PIB permalink, so a pattern wide enough to remove them would also
# have deleted real press releases.
SEED_HASH_PREFIX = "seed_hash_"

doomed = [r["id"] for r in (
    db().table("entries").select("id").like(
        "content_hash", f"{SEED_HASH_PREFIX}%").execute().data or [])]
kept = (db().table("entries").select("id", count="exact").execute().count or 0) - len(doomed)

for i in range(0, len(doomed), 50):
    db().table("entries").delete().in_("id", doomed[i:i + 50]).execute()
print(f"    removed {len(doomed)} seed entries, kept {kept} real ones")
PY
  )
fi

echo "==> Scraping${SOURCE:+ $SOURCE}"
api POST "/api/admin/scrape${SOURCE:+?source=$SOURCE}" 600

echo
echo "==> Summarising (10 per batch until the queue is empty)"
for i in $(seq 1 40); do
  out="$(api POST /api/admin/process 300)"
  processed="$(printf '%s' "$out" | sed -n 's/.*"processed":\([0-9]*\).*/\1/p')"
  printf '    batch %-3s %s\n' "$i" "$out"
  # Empty means the request failed; 0 means nothing left to do.
  [[ -z "$processed" || "$processed" == "0" ]] && break
done

echo
echo "==> Done"
api GET /api/stats 60
echo
