#! /bin/bash

cd "$(dirname "$0")" || exit 1

set -a
[ -f .env ] && source .env
set +a

uv sync
# Exclude paths that the backend itself writes to. Without these,
# uvicorn's reload watcher loops forever because every log write
# triggers a restart, which triggers another log write, ad infinitum.
uv run uvicorn backend.main:app --reload \
    --reload-exclude 'backend/logs/*' \
    --reload-exclude 'backend/data/*' \
    --reload-exclude 'data/*' \
    2>&1
