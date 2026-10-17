#!/usr/bin/env bash
# Start the parametric-sundial web app (backend + static frontend) on :8000.
set -euo pipefail
cd "$(dirname "$0")/backend"

PY="${PYTHON:-python3}"
if [ ! -d .venv ]; then
  echo "Creating virtualenv…"
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
./.venv/bin/pip install -q --upgrade pip
./.venv/bin/pip install -q -r requirements.txt

echo "→ http://localhost:8000"
exec ./.venv/bin/uvicorn app:app --reload --port "${PORT:-8000}"
