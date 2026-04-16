# ADR-001 — Ollama Homelab Sidecar Integration

**Status:** Accepted
**Date:** 2026-04-14
**Branch:** `claude/ollama-homelab-integration-0Tndu`

---

## Context

Chatsune's Phase 1 LLM stack exposes upstream inference providers via the
adapter registry in `backend/modules/llm/_adapters/`. Today the only
reachable providers are hosted (Ollama Cloud) or co-located with the
backend (Ollama Local). Both require the backend to speak outbound HTTP
to the provider.

Many privacy-minded users run their own Ollama instance at home, on a
GPU box that is:

- behind NAT / CGNAT / a consumer router
- without a stable public IP
- without port-forwarding capability or a managed tunnel account
- possibly powered off half the time

We want those users to be able to use their **home Ollama** as a
first-class upstream provider inside a **cloud-hosted Chatsune
installation** — transparently, alongside Ollama Cloud, with per-user
BYOK semantics.

This is the **#1 target deployment** (cloud Chatsune + home GPU). The
self-hosted-on-the-same-LAN case is already handled by `ollama_local`
and is explicitly out of scope for this ADR.

---

## Decision

Introduce a **homelab sidecar** — a small container the user runs next
to their home Ollama — which opens a persistent **outbound reverse
WebSocket** to the Chatsune backend using a **per-pairing pairing key**.
The backend multiplexes inference traffic back to the sidecar over this
same connection. While a sidecar is online, the backend exposes its
Ollama models as a standard upstream provider in the user's model
picker.

Each pairing becomes its own distinct provider namespace (e.g.
`ollama_homelab_a1b2c3d4`) so a user can have multiple homelabs
simultaneously without model-unique-ID collisions.

---

## Scope

### Phase 1 (this ADR)

- A user can create, list, rename, and revoke pairings for their own
  account.
- A user can run one or more sidecar containers, each bound to one
  pairing, each to one local Ollama endpoint.
- While a sidecar is connected, its Ollama models appear as a normal
  provider in the model picker — with the configured display name
  (e.g. "Wohnzimmer-GPU").
- Inference streams flow through the reverse WebSocket with the same
  `ProviderStreamEvent` contract the existing adapters use.
- Model lists are **pulled** by the backend on cache miss, identical to
  every other upstream provider (INS-001 semantics). No push channel.
- Offline sidecars degrade cleanly: the provider is hidden (or greyed
  out) until keepalive resumes.

### Later phases (explicitly out of scope)

- Multi-user sidecars (a homelab shared across a family) — Phase 2/3
- Non-Ollama home engines (llama.cpp, vLLM, MLX) — later
- Federation between Chatsune instances — later
- Self-healing tunnels, WebRTC fallback, IPv6-direct — later

---

## Architecture

### 1. Transport — Reverse WebSocket

The sidecar initiates an **outbound** WebSocket connection to the
Chatsune backend at `/ws/sidecar`, authenticating with its pairing
key. This is the only transport. No public URL, port forward, tunnel
subscription, or DynDNS is required on the user side.

All further traffic (model listings, inference requests, inference
streams, keepalives, errors) is multiplexed on this single connection
as framed JSON messages:

```
{ "type": "req",  "id": "<uuid>", "op": "list_models" }
{ "type": "req",  "id": "<uuid>", "op": "generate", "body": {...} }
{ "type": "res",  "id": "<uuid>", "ok": true,  "body": {...} }
{ "type": "res",  "id": "<uuid>", "ok": false, "error": {...} }
{ "type": "stream", "id": "<uuid>", "chunk": {...} }
{ "type": "stream_end", "id": "<uuid>" }
{ "type": "ping" } / { "type": "pong" }
```

Backend maintains a process-local **SidecarConnectionRegistry** keyed
by `pairing_id`, with per-request inbox/outbox channels so the adapter
can `await` on `request_id` like it would an HTTP round-trip.

**Keepalive:** one `ping` per minute from the sidecar; backend replies
with `pong`. Two missed pings → connection treated as dead, provider
marked offline, status event fan-out.

### 2. Data model — Collection + dynamic `provider_id`

We adopt **plan A+B combined**.

**New MongoDB collection:** `llm_sidecar_pairings`

```
{
  _id,                       # ObjectId
  user_id: str,              # owning user
  pairing_id: str,           # short, URL-safe, 8–12 chars, unique per user
  display_name: str,         # user-editable, e.g. "Wohnzimmer-GPU"
  pairing_key_hash: str,     # argon2id — NEVER the plaintext key
  pairing_key_hint: str,     # last 4 chars of the plaintext, for UI
  status: "pending" | "active" | "revoked",
  created_at: datetime,
  last_seen_at: datetime | None,
  revoked_at: datetime | None,
}
```

Unique index on `(user_id, pairing_id)`.

**Provider ID per pairing:** derived at runtime as
`ollama_homelab_<pairing_id>`. The `ADAPTER_REGISTRY` stays a static
dict; we introduce a **provider resolver** that first tries the static
dict, then falls back to parsing the `ollama_homelab_` prefix and
resolving the pairing from MongoDB.

This means:

- The model unique ID (INS-004) naturally carries the pairing:
  `ollama_homelab_a1b2c3d4:llama3.2`. No collision even if two homelabs
  both host `llama3.2`.
- Credentials storage **does not need extending**: the existing
  `llm_user_credentials` pattern is per (user_id, provider_id), and
  each pairing has a unique provider_id. We do not store the pairing
  key in `llm_user_credentials` at all — it lives in
  `llm_sidecar_pairings`.

### 3. Authentication — separate endpoint, hashed keys

- New endpoint `/ws/sidecar` accepts a `pairing_key` (URL query or
  handshake header). JWT is not accepted here.
- The endpoint resolves `pairing_id` from the key (via hash lookup),
  confirms `status == "active"`, and binds the connection to the
  pairing's owning `user_id`.
- **Pairing keys are never stored plaintext.** On creation they are
  shown to the user **once** in the UI; only `argon2id(hash)` is
  persisted, along with `pairing_key_hint` (last 4 chars) for user
  recognition.
- Revocation is instantaneous: flips `status = revoked`, drops any
  active connection, emits a status event.
- Pairing keys have **no access** to the normal user event stream,
  REST APIs, or any other user's data.

### 4. Concurrency

The existing `PER_USER` policy in `_concurrency.py:23` is reused
**as-is**. Because every pairing has a unique `provider_id`, the lock
key `(provider_id, user_id)` naturally becomes a per-pairing lock —
two homelabs of the same user run in parallel; two concurrent
inference requests to the *same* homelab serialize. No new
`ConcurrencyPolicy` value is introduced.

### 5. Model list cache

Identical semantics to INS-001: Redis TTL 30 minutes, lazy fetch on
cache miss. The `OllamaHomelabAdapter.fetch_models()` implementation
sends `{"op":"list_models"}` through the sidecar connection and
awaits the response. If the sidecar is offline the fetch returns an
empty list and the provider is treated as offline for the duration
of the TTL (the periodic reconnect will retrigger a fetch on the
next cache miss).

### 6. Lifecycle & status events

Extend `shared/topics.py`:

- `llm.sidecar.pairing_created`
- `llm.sidecar.pairing_revoked`
- `llm.sidecar.pairing_renamed`
- `llm.sidecar.connected`
- `llm.sidecar.disconnected`

`llm.provider.status_changed` (already in topics line 21) is reused
for provider-level online/offline fan-out so the model picker can
react without knowing about sidecars specifically.

### 7. Adapter

New file `backend/modules/llm/_adapters/_ollama_homelab.py`:

- `provider_id = "ollama_homelab"` at the class level — but note
  individual instances are resolved per pairing.
- `concurrency_policy = ConcurrencyPolicy.PER_USER`
- Holds a reference to the `SidecarConnectionRegistry` (injected at
  construction).
- `validate_key()` → meaningless here (the pairing key is validated
  at connection time, not at adapter level); returns True if the
  sidecar is currently connected.
- `fetch_models()` → RPC `list_models` through the sidecar.
- `stream_completion()` → RPC `generate` with streaming response; the
  adapter translates sidecar stream frames into
  `ProviderStreamEvent` objects and yields them.

---

## Security considerations

| Risk | Mitigation |
|---|---|
| Pairing key leak | Stored only as argon2id hash; shown once at creation; revocable; last-4-chars hint for UI recognition. |
| Sidecar impersonation | Reverse-only transport eliminates spoofing from the network; only the holder of the plaintext key can connect. |
| Lateral abuse (sidecar reaches non-LLM APIs) | `/ws/sidecar` is isolated: no fan-out of user event stream, no REST access, no access to another user's data. Only the inference op-codes are served. |
| Replay / multiple concurrent sidecars per pairing | Second connect on an already-connected pairing closes the older connection (last-wins) and emits a warning event to the user. |
| Malicious inference response | Sidecar output is treated exactly like any other upstream — it ends up in the user's own session. No trust elevation. |
| TLS | Backend terminates TLS as it already does; the sidecar verifies the server cert. No self-signed shortcuts. |

---

## New / extended contracts

### `shared/topics.py`

Add the five `llm.sidecar.*` topics listed above.

### `shared/events/llm.py`

Add `SidecarPairingCreatedEvent`, `SidecarPairingRevokedEvent`,
`SidecarPairingRenamedEvent`, `SidecarConnectedEvent`,
`SidecarDisconnectedEvent`.

### `shared/dtos/llm.py`

- `SidecarPairingDto` — `pairing_id`, `display_name`, `status`,
  `created_at`, `last_seen_at`, `pairing_key_hint`, `is_online: bool`
- `SidecarPairingCreatedDto` — includes the **one-time plaintext
  pairing key** in the REST response body only (never in events).

### MongoDB

- New collection: `llm_sidecar_pairings` (shape above).
- No migration needed — collection is created lazily.

### REST endpoints (LLM module)

- `POST /api/llm/sidecars` → create pairing, returns plaintext key once.
- `GET  /api/llm/sidecars` → list this user's pairings.
- `PATCH /api/llm/sidecars/{pairing_id}` → rename (display_name only).
- `DELETE /api/llm/sidecars/{pairing_id}` → revoke.

### WebSocket endpoints

- `/ws/sidecar?pairing_key=…` — new, pairing-key-auth.
- `/ws` — unchanged.

### Event bus fan-out rules (`backend/ws/event_bus.py`)

All new `llm.sidecar.*` topics target `[user_id]` only.

---

## Sidecar image

- Published to **`ghcr.io/<org>/chatsune-sidecar:latest`** (and
  semver-tagged releases), matching existing deployment convention.
- Minimal runtime: one process, reads `CHATSUNE_BACKEND_URL`,
  `CHATSUNE_PAIRING_KEY`, `OLLAMA_URL` (default
  `http://host.docker.internal:11434`).
- No persistence, no local state other than an in-memory request
  table. Restart-safe.
- Healthcheck endpoint on localhost for docker healthcheck and for the
  user's own visibility.
- Auto-reconnect with exponential backoff on disconnect.

---

## Open items deferred to implementation

- **Rate limits** on pairing creation per user (sanity cap, e.g. 10).
- **Sidecar → backend version skew handling** — include a protocol
  version in the handshake, refuse incompatible majors.
- **Metrics / observability** — sidecar RTT, inference duration,
  reconnect counts. Initial version can log only; dashboards later.
- **Inference cancellation** — client abort → stream_end with cancel
  flag forwarded to sidecar → sidecar cancels Ollama stream. Needs
  its own small contract note during implementation.

---

## Non-goals

- Replacing or deprecating `ollama_local`. That adapter remains the
  right choice when Chatsune and Ollama run on the same host.
- Providing a hosted tunnel service. The reverse-WebSocket model makes
  this unnecessary.
- Exposing sidecar operation to any user except its owner.

---

## Consequences

**Positive.** Cloud Chatsune gains a native way to use private home
hardware for inference, preserving the BYOK privacy model (INS-002)
without any external tunnel dependency. The model-unique-ID scheme
(INS-004) absorbs the multi-pairing case naturally. Existing
concurrency, cache, and event infrastructure are reused.

**Negative.** A new connection type lives alongside the user WebSocket
and must be operated, monitored, and kept safe. The adapter pattern
grows a first case of RPC-through-WebSocket rather than plain
upstream HTTP — this is a genuine new capability in the LLM module,
not a copy-paste of an existing adapter.

**Reversible?** Yes. Pairings, the collection, the endpoint, and the
adapter can be removed without affecting any other module, since the
module boundary rule (CLAUDE.md §1) means no other module imports
them.
