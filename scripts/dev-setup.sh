#!/usr/bin/env bash
#
# Rebuild everything a fresh clone is missing.
#
#   ./scripts/dev-setup.sh
#
# .venv, node_modules and both .env files are gitignored, so cloning this repo
# gives you the code and none of the things needed to run it. This puts them
# back and tells you which secrets are still blank.

set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> Backend virtualenv"
if [[ ! -x backend/.venv/bin/python ]]; then
  python3 -m venv backend/.venv
fi
backend/.venv/bin/pip install -q --upgrade pip
backend/.venv/bin/pip install -q -r backend/requirements.txt
echo "    ok"

echo "==> Frontend packages"
(cd frontend && npm install --silent)
echo "    ok"

for pair in "backend/.env:backend/.env.example" "frontend/.env.local:frontend/.env.example"; do
  target="${pair%%:*}"; template="${pair##*:}"
  if [[ ! -f "$target" ]]; then
    cp "$template" "$target"
    echo "==> Created $target from $template"
  fi
done

echo
echo "==> Secrets still to fill in"
backend/.venv/bin/python - <<'PY'
import re, sys
sys.path.insert(0, "backend")

REQUIRED = {
    "backend/.env": ["SUPABASE_URL", "SUPABASE_SERVICE_KEY", "GROQ_API_KEY", "ADMIN_API_KEY"],
    "frontend/.env.local": ["NEXT_PUBLIC_SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_ANON_KEY"],
}
# Values carried over from the templates are placeholders, not real settings.
PLACEHOLDER = re.compile(r"^(|xxx.*|eyJ\.\.\..*|sk-ant-x+|re_x+|https://xxx\..*)$")

missing = False
for path, keys in REQUIRED.items():
    values = {}
    try:
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                values[k.strip()] = v.split("#")[0].strip()
    except FileNotFoundError:
        continue
    for k in keys:
        v = values.get(k, "")
        if not v or PLACEHOLDER.match(v):
            print(f"    {path:<22} {k}")
            missing = True

if not missing:
    print("    none — both files look complete")
PY

echo
echo "Next:"
echo "  1. Fill in anything listed above."
echo "  2. Paste supabase/setup_all.sql into the Supabase SQL editor (once per project)."
echo "  3. cd backend && .venv/bin/uvicorn app.main:app --port 8000 --reload"
echo "  4. cd frontend && npm run dev"
echo "  5. ./scripts/real-data.sh --purge     # real notifications, no fixtures"
