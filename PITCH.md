# Chatsune — A Privacy-First, Self-Hosted AI Companion Platform

> Prototype 3. Hard lessons. Clean architecture.

---

## What It Is

Chatsune is a **multi-user, self-hosted AI companion platform** built around local and
cloud-based LLM inference. It is designed for people who want a persistent, personalised
AI companion without giving their data to a third-party SaaS product.

Think: your own private ChatGPT, but with long-term memory, personas, knowledge bases,
sandboxed tool execution, and a real event-driven architecture — deployed on your own
hardware via Docker Compose.

---

## Core Design Philosophy

- **Privacy-first** — your data never leaves infrastructure you control
- **BYOK (Bring Your Own Key)** — users manage their own API keys; no shared admin secrets
- **Event-first** — the frontend is a pure view; every state change produces an event
- **Modular Monolith** — strict module boundaries, no microservice overhead
- **No polling** — if you think you need polling, you need an event instead

---

## What Is Actually Built

### Long-Term Memory ("Dreaming")

The most interesting part. Chatsune builds a persistent memory of each persona's
interactions with you over time.

- Conversations are scanned periodically by a background extraction job that creates
  raw journal entries from significant user statements
- Entries accumulate until a **memory consolidation job** ("dreaming") kicks in:
  hard trigger at ≥ 25 entries, soft trigger at ≥ 10 entries + 6 hours since last dream
- Consolidation assembles a token-budgeted prose summary, updates the memory body,
  and clears the entries — the persona wakes up with a more refined long-term picture
- Memory body + recent uncommitted entries are injected as RAG context at inference time
- Memory body versioned with rollback on consolidation failure

This is not a naive "stuff everything into the context" approach. It is a two-tier system:
fresh episodic entries for recent context, consolidated prose for long-term recall.

### Multi-Model LLM Support

- **Ollama Local**: discovers models from a running Ollama instance on your network,
  serialises concurrent requests via a per-adapter async lock
- **Ollama Cloud**: BYOK per-user API keys, encrypted at rest with Fernet
- Three-layer model metadata: provider-sourced (Redis, ephemeral) → admin curation
  (MongoDB, persistent) → user config (MongoDB, per-user personalisation)
- Model capabilities tracked: vision support, native reasoning (CoT), tool calls
- **Vision fallback**: non-vision models automatically delegate image description to
  a vision-capable model, cache the result, feed it back — transparent to the user

### Tool Loop with Client-Side Execution

- Standard server-side tools: **web search**, **web fetch**, **knowledge search**,
  **artefact CRUD** (code, docs, Mermaid diagrams, HTML, SVG, JSX)
- Up to 5 tool iterations per inference request, with refusal detection at each step
- **`calculate_js`**: a client-side tool that executes arbitrary JavaScript in an
  isolated Web Worker sandbox (no DOM, no network, no persistent state)
  — arithmetic, date maths, text processing, JSON manipulation, all zero-latency
- Tool dispatch bridged over WebSocket: server asks the user's browser to execute,
  browser runs isolated Worker, result returned to server, fed back to the model

### Knowledge Bases

- Per-persona document libraries with chunk-level vector embeddings
- Embeddings generated locally by **Arctic Embed M v2.0** via ONNX Runtime —
  768-dimensional vectors, never sent to any external API
- Batch embedding queue with Redis Streams, priority scheduling, lazy model init
- Redis LRU cache for query embeddings (count-bounded to 16 384 entries,
  vectors stored as packed binary — 4 KB vs 15 KB for JSON)
- **MongoDB Vector Search** on the chunk collection; no external vector database needed

### Event-Driven WebSocket Architecture

Every state change in the backend publishes a typed event. The single WebSocket
connection per user receives all relevant events in real time.

- Structured event envelope: `id`, `type` (from a typed Topics constant), `sequence`,
  `scope` (global / persona / session / user), `correlation_id`, `timestamp`, `payload`
- **113 event topics** covering the full domain: auth, chat, memory, knowledge,
  artefacts, jobs, settings, debug, errors
- Events persisted in **Redis Streams** with 24-hour TTL
- On reconnect, the client sends its last received sequence; the backend replays
  all missed events from all relevant streams, merged and time-ordered
- Fan-out rules table: broadcast, role-based delivery, explicit user targeting

### Background Job System

- Redis Streams consumer group for the job queue
- Three job types: title generation, memory extraction, memory consolidation
- Per-user concurrency control: new user action cancels any in-flight inference
- Safeguards: per-user rate limiting (50 calls / 60 s), circuit breaker
  (5 failures / 300 s → 900 s open), daily token budget (5 M tokens), queue cap
- Emergency kill-switch for Ollama Cloud (env var, reloadable without restart)
- Idempotent execution via `execution_token`

### Persona System

- Named personas with system prompts, avatars (uploaded or generated monogram),
  soft-delete, and reordering
- Each persona has its own memory body and journal
- Three-layer system prompt hierarchy at inference time:
  global admin guardrails → user model config additions → persona prompt
- **Soft Chain-of-Thought** injection: when a model lacks native reasoning,
  an analytical + relational reasoning block is injected automatically

### Authentication

- JWT access tokens (15 min) + httpOnly refresh cookies (30 days)
- Token expiry warning sent as an event 2 minutes before expiry
- Token refresh over the existing WebSocket — no reconnect, no visible disruption
- Multiple concurrent sessions per user supported
- Master admin bootstrapped via one-time PIN; no hard-coded credentials

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 19 + TypeScript + Vite 8 + Tailwind CSS 4 |
| State management | Zustand 5 |
| Markdown | react-markdown + KaTeX + Shiki + Mermaid |
| Backend | Python 3.12 + FastAPI (async-first) |
| Models / Validation | Pydantic v2 |
| Database | MongoDB 7.0 with Single-Node Replica Set |
| Vector Search | MongoDB Atlas Vector Search (local) |
| Cache / Queue | Redis 7 (Streams, LRU cache, locks) |
| Embeddings | Arctic Embed M v2.0 — ONNX Runtime, local inference |
| Token counting | TikToken |
| Crypto | Fernet (API key encryption), bcrypt + PyJWT |
| Logging | structlog (JSON in Docker, pretty console in dev) |
| Deployment | Docker Compose — MongoDB Atlas Local + Redis Alpine |
| Package managers | pnpm (frontend), uv (backend) |

---

## Repository Structure (Abbreviated)

```
chatsune/
  frontend/                  ← Vite + React + TSX + Tailwind
  backend/
    main.py                  ← single FastAPI entrypoint
    modules/
      user/       chat/      artefact/   bookmark/
      persona/    memory/    knowledge/  embedding/
      llm/        tools/     websearch/  storage/
      settings/   project/   debug/      job/
    ws/                      ← WebSocket manager + router + event bus
  shared/
    events/                  ← typed event models (Pydantic)
    dtos/                    ← cross-module data contracts
    topics.py                ← 113 typed event constants
  docker-compose.yml
```

Module boundaries are strictly enforced: internal files are prefixed with `_`
and may never be imported from outside the module. Cross-module access goes
through the public API in `__init__.py` only.

---

## How to Run

```bash
# Start infrastructure (MongoDB + Redis)
docker compose up -d

# Backend
uv run uvicorn backend.main:app --reload

# Frontend
cd frontend && pnpm install && pnpm dev
```

One `.env` file, one `docker-compose.yml`, no external services required.

---

## What Makes It Different

| Feature | Notes |
|---|---|
| Local embeddings | No embedding API. ONNX, runs on CPU. |
| Dreaming (memory consolidation) | Background job condenses episodic memory into prose on a schedule |
| Client-side tool sandbox | JavaScript execution in isolated Web Worker — zero latency, zero server cost |
| Vision model fallback | Non-vision models silently delegate to a vision model and cache the description |
| Three-layer model metadata | Provider → admin curation → per-user config, merged at read time |
| Event replay on reconnect | 24-hour event history in Redis Streams; no data loss on disconnect |
| Soft Chain-of-Thought | Reasoning block injected when model lacks native CoT |
| Tool iteration loop | Up to 5 model→tool→model iterations per request |
| BYOK | Every user has their own keys; admin has no visibility into user credentials |
| Modular monolith | Module contracts enforced in code, not just convention |

---

## Status

Active development. Core platform is functional end-to-end:
auth, chat with streaming, memory, knowledge, artefacts, tools, personas, file uploads,
background jobs, WebSocket event bus. PWA-ready (installable on mobile).

Not yet implemented: OpenRouter adapter, Brave/Kagi search, fully polished admin UX.

---

## Licence

GPL-3.0
