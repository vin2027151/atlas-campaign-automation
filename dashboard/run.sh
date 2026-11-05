#!/usr/bin/env bash
# Start the Atlas Ops dashboard on port 4500.
set -euo pipefail
cd "$(dirname "$0")"
if [ -d .venv ]; then . .venv/bin/activate; fi
if [ ! -f data/state.json ]; then python3 -m data.seed; fi
exec uvicorn app:app --host 0.0.0.0 --port 4500 "$@"
