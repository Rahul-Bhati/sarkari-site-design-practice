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
ADMIN_KEY="$(backend/.venv/bin/python -c \
  'import sys; sys.path.insert(0, "backend"); from app.config import Settings; print(Settings().admin_api_key)')"

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
  backend/.venv/bin/python - <<'PY'
import sys
sys.path.insert(0, "backend")
from app.database import db

# The seed rows are the ones whose permalinks were invented for the fixture.
FAKE = ("/bid/GEM-2026-B-", "eproc.rajasthan.gov.in/tender/", "example.gov.in")
rows = db().table("entries").select("id,original_url").execute().data or []
doomed = [r["id"] for r in rows
          if any(f in (r.get("original_url") or "") for f in FAKE)]
for i in range(0, len(doomed), 50):
    db().table("entries").delete().in_("id", doomed[i:i + 50]).execute()
print(f"    removed {len(doomed)} seed entries, kept {len(rows) - len(doomed)} real ones")
PY
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
