#! /bin/bash

cd "$(dirname "$0")" || exit 1

set -a
[ -f .env ] && source .env
set +a

uv sync
uv run uvicorn backend.main:app --reload 2>&1
