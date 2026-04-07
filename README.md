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
| `MONGODB_URI` | MongoDB connection string — must include `replicaSet=rs0` | `mongodb://mongodb:27017/chatsune?replicaSet=rs0` |
| `REDIS_URI` | Redis connection string | `redis://redis:6379/0` |
| `UPLOAD_ROOT` | Root path for file uploads | `/data/uploads` |
| `UPLOAD_QUOTA_BYTES` | Per-user upload quota in bytes | `1073741824` (1 GB) |
| `AVATAR_ROOT` | Root path for persona avatars | `/data/avatars` |
| `EMBEDDING_MODEL_DIR` | Where embedding model weights are cached | `./data/models` |
| `EMBEDDING_BATCH_SIZE` | Batch size for the embedding worker | `8` |
| `COOKIE_DOMAIN` | Optional parent domain for the refresh-token cookie | `.example.com` |

For the LLM test harness, place your Ollama Cloud key in `.llm-test-key`
(plain text, gitignored) in the project root.

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

## Licence

GPL-3.0 — see [LICENSE](LICENSE).
