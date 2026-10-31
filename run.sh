#!/usr/bin/env bash
# Starts the Kipu Shadow API on http://0.0.0.0:${PORT:-9000}/v1.
# Single uvicorn worker: run jobs live in this process.
set -euo pipefail

root="$(cd "$(dirname "$0")" && pwd)"
cd "$root"

if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi

stamp=".venv/.requirements.sha"
current="$(shasum requirements.txt | cut -d' ' -f1)"
if [[ ! -f "$stamp" || "$(cat "$stamp")" != "$current" ]]; then
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt
  echo "$current" > "$stamp"
fi

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

exec .venv/bin/uvicorn --factory app.main:create_app --host 0.0.0.0 --port "${PORT:-9000}"
