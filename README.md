# Chatsune

Privacy-first, self-hosted, multi-user AI companion platform.

Chatsune is a modular monolith backend (FastAPI) with a React/TSX frontend.
All chat sessions, personas, memories and artefacts live on your own
infrastructure. LLM inference is delegated to upstream providers behind a
pluggable adapter layer (currently Ollama Cloud, BYOK per user).

This is **Prototype 3**. The architecture is intentionally strict — see
[CLAUDE.md](CLAUDE.md) and [INSIGHTS.md](INSIGHTS.md) before changing anything.

---

## What's already in place

### Backend modules (`backend/modules/`)

- **user** — authentication (JWT access + refresh cookie), user CRUD,
  master admin bootstrap, multi-user support
- **chat** — chat sessions, message history, prompt assembly, soft chain-of-thought
  parser, orchestrator, vision fallback for non-vision models
- **persona** — personas with avatars (uploaded images or generated monograms)
- **memory** — long-term memory store and consolidation
- **knowledge** — knowledge base entries attached to personas
- **artefact** — artefacts produced during chats
- **bookmark** — bookmarking inside conversations
- **project** — grouping of chats / personas into projects
- **journal** — persona journal entries (lasting facts only)
- **embedding** — local embedding subsystem (Arctic Embed M v2.0, ONNX,
  priority queue) used for vector search in MongoDB
- **llm** — provider-agnostic LLM client; first adapter is Ollama Cloud.
  Model IDs follow `<provider>:<model_slug>` (e.g. `ollama_cloud:llama3.2`)
- **websearch** — pluggable web-search adapters
- **tools** — tool registry, group toggling, executor dispatch
- **storage** — file uploads with per-user quota
- **settings** — per-user settings

### Frontend (`frontend/src/features/`)

- **chat** — chat UI, sidebar, persona picker, model picker, new-chat row
- **memory** — memory browser
- **knowledge** — knowledge management
- **artefact** — artefact viewer

### Infrastructure

- **MongoDB 7.0** as a single-node replica set (`rs0`) — required for
  transactions and vector search. Provided by `mongodb/mongodb-atlas-local`.
- **Redis 7** — refresh tokens, session cache, Redis Streams for event
  catchup on reconnect (24 h TTL)
- **WebSocket** event bus — one connection per user, all server→client
  state changes flow through it (no polling, no REST follow-ups)

### Tooling

- **LLM test harness** at `backend/llm_harness/` — standalone CLI for
  direct LLM calls against Ollama Cloud (no DB, no auth). Use it for
  prompt iteration and provider debugging.
- **Obsidian vault** in `obsidian/` for design notes

---

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- [uv](https://docs.astral.sh/uv/) — Python package manager
- [pnpm](https://pnpm.io/) — frontend package manager
- Node.js 20+ (for the frontend dev server)

---

## Quick start (recommended local dev setup)

The most ergonomic local setup is: **infrastructure in Docker, backend and
frontend running natively with hot reload.**

### 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

- `MASTER_ADMIN_PIN` — any string, used once for the initial admin setup
- `JWT_SECRET` — generate with `openssl rand -hex 32`
- `ENCRYPTION_KEY` — generate with
  `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- `KDF_PEPPER` — generate with
  `python -c "import secrets, base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"`

### 2. Start infrastructure (MongoDB + Redis)

```bash
docker compose up -d
```

This brings up the MongoDB replica set and Redis with healthchecks.
Data is persisted in named volumes (`mongodb_data`, `redis_data`).

### 3. Start the backend

```bash
./start-backend.sh
```

This runs `uv sync` and then `uvicorn backend.main:app --reload` on
`http://localhost:8000`.

Health check:

```bash
curl http://localhost:8000/api/health
# {"status":"ok"}
```

### 4. Start the frontend

In a second terminal:

```bash
./start-frontend.sh
```

Runs `pnpm install` and `pnpm run dev`. The Vite dev server prints
its URL (typically `http://localhost:5173`).

#### Vosk model (one-time setup)

The voice-command OFF-state uses a local Vosk speech recogniser. The
~40 MB model is downloaded by a setup script:

```bash
cd frontend
pnpm run vosk:download
```

The script is idempotent — re-running is a no-op once the model is in
`frontend/vendor/vosk-model/` (gitignored). The Docker build runs this
script automatically.

### 5. Create the master admin (one-time)

```bash
curl -X POST http://localhost:8000/api/setup \
  -H "Content-Type: application/json" \
  -d '{
    "pin": "your-configured-pin",
    "username": "admin",
    "email": "admin@example.com",
    "password": "your-secure-password"
  }'
```

Then open the frontend URL and log in.

### 6. Configure your LLM provider

Chatsune uses **BYOK** — each user supplies their own Ollama Cloud API
key in the settings UI after logging in. Without a key, no chat
inference will work.

---

## Full-stack Docker variant

If you want everything in Docker (no native Python/Node), there is an
alternative compose file:

```bash
docker compose -f docker-compose-fullstack.yml up -d
```

Use this for production-like runs or when validating the container
build. For day-to-day development the split setup above is faster
because of hot reload.

---

## Environment Variables

| Variable | Description | Example |
|---|---|---|
| `MASTER_ADMIN_PIN` | PIN for initial master admin setup | `change-me-1234` |
| `JWT_SECRET` | Secret for signing JWTs (`openssl rand -hex 32`) | random hex string |
| `ENCRYPTION_KEY` | Fernet key for encrypting per-user API keys at rest | Fernet key |
| `KDF_PEPPER` | 32-byte pepper (urlsafe-base64) for the `/kdf-params` user-enumeration defence | urlsafe-base64 string |
| `MONGODB_URI` | MongoDB connection string — must include `replicaSet=rs0` | `mongodb://mongodb:27017/chatsune?replicaSet=rs0` |
| `REDIS_URI` | Redis connection string | `redis://redis:6379/0` |
| `UPLOAD_ROOT` | Root path for file uploads | `/data/uploads` |
| `UPLOAD_QUOTA_BYTES` | Per-user upload quota in bytes | `1073741824` (1 GB) |
| `AVATAR_ROOT` | Root path for persona avatars | `/data/avatars` |
| `EMBEDDING_MODEL_DIR` | Where embedding model weights are cached | `./data/models` |
| `EMBEDDING_BATCH_SIZE` | Batch size for the embedding worker | `8` |
| `COOKIE_DOMAIN` | Optional parent domain for the refresh-token cookie | `.example.com` |
| `LLM_STREAM_ABORT_SECONDS` | Maximum idle time in seconds the LLM upstream stream may stay silent before we declare it aborted and surface an error toast. Must be larger than 30 (the hard-coded slow-phase threshold). Increase if you use large cloud models on slow providers. | `120` |

For the LLM test harness, place your Ollama Cloud key in `.llm-test-key`
(plain text, gitignored) in the project root.

### Per-user key infrastructure environment

Chatsune requires an additional pepper used to keep the `POST /api/auth/kdf-params` endpoint indistinguishable between real and unknown usernames:

- `KDF_PEPPER` — 32-byte pepper, urlsafe-base64. Generate with:

  ```bash
  python -c "import secrets, base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
  ```

  This is separate from `ENCRYPTION_KEY` (which covers operational secrets like integration API keys). Losing `KDF_PEPPER` does not decrypt any user data — it only weakens the user-enumeration defence.

### Authentication & end-to-end encryption foundations

Chatsune uses client-side Argon2id (Web Worker) + HKDF to derive separate auth and key-wrapping hashes from the user password. Every account carries a per-user Data Encryption Key (DEK) wrapped twice — once under a password-derived key, once under a client-generated recovery key. See `E2EE_PHASE_1_ANNOUNCEMENT.md` in the repo root for a user-facing explanation. No user data is encrypted in this release; the key-management plumbing is in place for collection-by-collection rollout in later releases.

### Safeguards (background jobs)

The background-job system enforces a set of hard safeguards that protect
users from runaway cost caused by bugs, retries, or a misbehaving upstream
provider. Every value can be tuned via environment variables and reloaded
by restarting the backend — no redeploy required.

| Variable | Purpose | Default | Acceptable values | When to change |
|---|---|---|---|---|
| `OLLAMA_CLOUD_EMERGENCY_STOP` | Global kill-switch for the Ollama Cloud provider. When enabled, the LLM adapter rejects all new Ollama Cloud requests immediately. | `false` | `true` / `false` | Flip to `true` in an emergency (upstream outage, unexpected cost spike). Takes effect on backend reload — no code redeploy needed. |
| `JOB_RATE_LIMIT_WINDOW_SECONDS` | Rolling window used by the per-user/provider rate limiter. | `60` | Positive integer (seconds) | Lengthen for slower sustained limits, shorten for stricter bursts. |
| `JOB_RATE_LIMIT_MAX_CALLS` | Maximum LLM calls a single user may issue against one provider within the window. | `50` | Non-negative integer; `0` disables the limiter | Lower for very small tester groups, raise once usage patterns are known. |
| `JOB_QUEUE_CAP_PER_USER` | Maximum queued background jobs per user before new submits are rejected. | `10` | Non-negative integer; `0` disables the cap | Raise if legitimate bursts are being rejected; keep low during the initial test release. |
| `JOB_DAILY_TOKEN_BUDGET` | Daily token budget per user across all background-job LLM calls. Counter resets at 00:00 UTC. | `5000000` | Non-negative integer; `0` disables the budget | Tighten for untrusted testers, loosen for power users once behaviour is understood. |
| `JOB_CIRCUIT_FAILURE_THRESHOLD` | Failures tolerated within the circuit window before the provider circuit opens. | `5` | Non-negative integer; `0` disables the breaker | Raise if a flaky provider trips the breaker too eagerly. |
| `JOB_CIRCUIT_WINDOW_SECONDS` | Rolling window over which circuit-breaker failures are counted. | `300` | Positive integer (seconds) | Lengthen to be more forgiving, shorten to react faster to sudden failure bursts. |
| `JOB_CIRCUIT_OPEN_SECONDS` | How long the circuit stays open after tripping, during which new requests to the affected provider are rejected fast. | `900` | Positive integer (seconds) | Shorten for fast recovery, lengthen to give a struggling upstream more time to heal. |
| `LLM_STREAM_ABORT_SECONDS` | Idle-timeout before a silent LLM stream is aborted. | `120` | Positive integer (seconds); must exceed 30 | Increase if long artefact generations trip the abort on slow cloud providers. |

Note: `OLLAMA_CLOUD_EMERGENCY_STOP=true` is the fastest way to stop all
Ollama Cloud traffic in an incident. Edit `.env`, reload the backend, and
the adapter starts refusing new requests immediately — no code redeploy
required.

---

## Development

```bash
# Install backend dependencies
uv sync

# Type-check / build the frontend
cd frontend && pnpm install && pnpm run build && cd ..

# Run backend tests (requires MongoDB + Redis up)
docker compose up -d
uv run pytest tests/ -v
```

Build verification rules (see CLAUDE.md):

- Frontend changes → `pnpm run build` (or `pnpm tsc --noEmit`) must be clean
- Backend changes → `uv run python -m py_compile <file>` for quick syntax checks

### LLM test harness

```bash
# Simple prompt
uv run python -m backend.llm_harness --model llama3.2 \
  --message '{"role":"user","content":"Hello"}'

# Reproducible scenario from a JSON file
uv run python -m backend.llm_harness --from tests/llm_scenarios/simple_hello.json
```

---

## Architecture

- [CLAUDE.md](CLAUDE.md) — hard architectural rules (module boundaries,
  shared contracts, event-first design, no cross-module DB access)
- [INSIGHTS.md](INSIGHTS.md) — non-obvious design decisions and the
  reasoning behind them
- [docs/](docs/) — ADRs

---

## Logging

Chatsune uses [structlog](https://www.structlog.org/) with two sinks that
can run simultaneously:

- **Console** — pretty, colourful output in local dev; JSON lines in
  Docker (picked up by Grafana/Loki). Controlled by `LOG_CONSOLE` and
  `LOG_CONSOLE_FORMAT`.
- **Rotating file** — JSON lines at `backend/logs/chatsune.log`, rotated
  daily with 14 backups retained. Off by default inside Docker.
  Controlled by `LOG_FILE`, `LOG_FILE_PATH`, `LOG_FILE_BACKUP_COUNT`.
  Ideal for `lnav` or `jq`.

Every record carries `timestamp`, `level`, `logger` (dotted namespace
such as `chatsune.jobs.consumer`), `event` (stable short identifier such
as `job.enqueued`), plus any bound context (`correlation_id`, `job_id`,
`job_type`, `user_id`, `lock_key`). Context is propagated automatically
via `structlog.contextvars`, so downstream log lines inherit it without
needing to repeat the fields at every call site.

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Root log level |
| `LOG_CONSOLE` | `1` | Enable console sink |
| `LOG_CONSOLE_FORMAT` | `pretty` | `pretty` or `json` |
| `LOG_FILE` | `1` | Enable rotating file sink |
| `LOG_FILE_PATH` | `backend/logs/chatsune.log` | File path |
| `LOG_FILE_BACKUP_COUNT` | `14` | Daily rotations retained |
| `LOG_LEVEL_UVICORN_ACCESS` | `WARNING` | HTTP access noise threshold |
| `LOG_LEVEL_THIRD_PARTY` | `WARNING` | `httpx`, `httpcore`, `pymongo` |

Docker compose files override `LOG_CONSOLE_FORMAT=json` and `LOG_FILE=0`
for the backend service.

### Filtering examples

```bash
# Everything from the job consumer
jq 'select(.logger=="chatsune.jobs.consumer")' backend/logs/chatsune.log

# One specific job end-to-end
jq 'select(.job_id=="abc123")' backend/logs/chatsune.log

# Lock contention only
jq 'select(.event=="job.lock.contended")' backend/logs/chatsune.log
```

---

## Licence

GPL-3.0 — see [LICENSE](LICENSE).
