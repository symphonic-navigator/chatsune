#!/usr/bin/env bash
# Local dev environment bootstrap for Chatsune.
#
# Idempotent: when `.env` already exists, this script does not overwrite
# it — re-run it freely. To start over, delete `.env` first.
#
# What it does:
#   1. Copy `.env.example` to `.env`
#   2. Generate real values for the three secrets (JWT_SECRET,
#      ENCRYPTION_KEY, KDF_PEPPER)
#   3. Rewrite Docker-internal hostnames (mongodb, redis) to `localhost`
#      so the backend can connect from the host
#   4. Rewrite container storage paths (/data/...) to repo-local
#      (./data/...) so uploads/avatars land in a gitignored directory
#   5. Create `data/uploads` and `data/avatars`
#
# What it does NOT do:
#   - `uv sync`, `pnpm install`, or `docker compose up` — start those
#     yourself when you're ready (`./start-backend.sh` already calls
#     `uv sync`)
#   - Set provider API keys — those are real subscriptions you have to
#     paste in yourself (xAI, Tensorix, Ollama Cloud, ...)

set -euo pipefail
cd "$(dirname "$0")"

ENV_FILE=".env"
EXAMPLE_FILE=".env.example"

# ---- Step 1: copy example, or skip if .env already exists --------------------

if [[ -f "$ENV_FILE" ]]; then
    echo "✓ $ENV_FILE already exists — leaving it alone."
    echo "  (If you want a fresh setup, delete $ENV_FILE and re-run.)"
    echo ""
else
    if [[ ! -f "$EXAMPLE_FILE" ]]; then
        echo "✗ $EXAMPLE_FILE not found. Are you in the project root?" >&2
        exit 1
    fi

    cp "$EXAMPLE_FILE" "$ENV_FILE"
    echo "✓ Created $ENV_FILE from $EXAMPLE_FILE"

    # ---- Step 2: generate real secrets ---------------------------------------
    # JWT_SECRET: 32 random bytes as hex (64 chars).
    # ENCRYPTION_KEY: Fernet key (32 random bytes, url-safe base64, with
    #   padding) — produced via Python stdlib so we don't need `uv sync`
    #   to have run yet.
    # KDF_PEPPER: 32 random bytes, url-safe base64, no padding.
    JWT_SECRET=$(openssl rand -hex 32)
    ENCRYPTION_KEY=$(python3 -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')
    KDF_PEPPER=$(openssl rand -base64 32 | tr -d '=' | tr '/+' '_-')

    # ---- Step 3 & 4: patch .env ----------------------------------------------
    # `|` is safe as a sed delimiter because none of our generated values
    # nor the literal paths contain it.
    sed -i \
        -e "s|^MASTER_ADMIN_PIN=.*|MASTER_ADMIN_PIN=1234|" \
        -e "s|^JWT_SECRET=.*|JWT_SECRET=${JWT_SECRET}|" \
        -e "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=${ENCRYPTION_KEY}|" \
        -e "s|^KDF_PEPPER=.*|KDF_PEPPER=${KDF_PEPPER}|" \
        -e "s|^MONGODB_URI=mongodb://mongodb:|MONGODB_URI=mongodb://localhost:|" \
        -e "s|^REDIS_URI=redis://redis:|REDIS_URI=redis://localhost:|" \
        -e "s|^UPLOAD_ROOT=/data/|UPLOAD_ROOT=./data/|" \
        -e "s|^AVATAR_ROOT=/data/|AVATAR_ROOT=./data/|" \
        "$ENV_FILE"

    echo "✓ Generated JWT_SECRET, ENCRYPTION_KEY, KDF_PEPPER"
    echo "✓ Rewrote MONGODB_URI, REDIS_URI hosts to localhost"
    echo "✓ Rewrote UPLOAD_ROOT, AVATAR_ROOT to ./data/..."
    echo ""
fi

# ---- Step 5: create local storage directories --------------------------------
# data/ is in .gitignore — nothing inside it gets committed.
mkdir -p data/uploads data/avatars
echo "✓ Ensured data/uploads and data/avatars exist"
echo ""

echo "=== Dev setup complete ==="
echo ""
echo "⚠  MASTER_ADMIN_PIN is set to '1234' for dev convenience."
echo "   Change it in .env before deploying anywhere non-local."
echo ""
echo "Next steps:"
echo "  1. (optional) Edit .env to add provider API keys you have"
echo "       (xAI, Tensorix, Ollama Cloud, OpenRouter, Novita, ...)"
echo "  2. docker compose up -d     # mongodb + redis"
echo "  3. ./start-backend.sh       # also runs 'uv sync'"
echo "  4. cd frontend && pnpm install && pnpm dev"
