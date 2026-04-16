# Community Provisioning & Chatsune Sidecar Protocol (CSP) v1

**Status:** Draft (brainstormed 2026-04-16)
**Supersedes:** `docs/adr-001-homelab-sidecar.md` (mark that document as *Superseded by this spec* on merge).
**Scope:** Host-side data model, wire protocol, consumer-side adapter, and UI.
The sidecar implementation ships in a separate repository; this document
specifies only what the sidecar must do, not how.

---

## 1. Context & Motivation

Chatsune's consumer-side LLM stack speaks to each upstream through an
**Adapter + Connection** pair (INS-016). Connections today assume the
backend can reach the upstream by outbound HTTP: this works for Ollama
Cloud and self-hosted-on-same-LAN Ollama, but breaks the moment a user
wants to use **their own hardware from a cloud-hosted Chatsune
install** — the common case is a GPU box behind CGNAT, dynamic IP, no
port-forwarding.

Initial work (ADR-001) specced a narrow "ollama_homelab" provider
tailored to that one scenario. Since then the feature has grown in two
directions:

- **Invitation-based sharing.** A host user (Alice) wants to let
  specific other users (Bob, later Charlie) borrow her compute. This
  is not a marketplace, not a public discovery feature, not "free for
  all" — it is "Alice invites Bob because she trusts him."
- **Multi-engine reality.** Ollama is not the only local runtime worth
  supporting. LM Studio is popular in the enthusiast segment, vLLM
  dominates high-throughput self-hosting, and llama.cpp's `server` is
  the lightweight reference. All four must be in scope long-term even
  if only Ollama ships first.

These two pressures turn the feature from *one extra adapter* into a
**proper subsystem**: a Host-side "Community Provisioning" data model,
a dedicated wire protocol (CSP), a generic consumer-side `community`
adapter, and an out-of-tree sidecar.

Critically, the design must not leak engine-specific concepts across
the backend ↔ sidecar boundary. The sidecar is the *only* place that
speaks Ollama-API or LM-Studio-API or llama.cpp-API — the Chatsune
backend only ever speaks CSP.

---

## 2. Scope

### In scope for v1

- Data model for *Homelabs* (host-owned) and *API-Keys* (host-issued,
  per-consumer).
- CSP v1 wire protocol covering: handshake, heartbeat, model listing,
  chat completion streaming, tool-call streaming, multimodal input,
  reasoning-stream as a separate channel, cancellation, and
  structured errors.
- `community` adapter in `backend/modules/llm/_adapters/` with URL
  scheme `homelab://<homelab_id>` plus a separate API-key field.
- Host-side UI: a new **Community Provisioning** section under
  Settings, with full CRUD for Homelabs and API-Keys.
- Per-API-key **model allowlist** — the only access-control primitive
  in v1, required because loading an unexpected 120B model can OOM
  the host's GPU.
- Sidecar-declared **max concurrent requests** in the handshake; the
  backend queues/limits accordingly using the existing per-Connection
  semaphore infrastructure (INS-017).
- A reference sidecar image (separate repo) that speaks CSP ⇄ Ollama.

### Deferred to v2+

- Embeddings over CSP. Chatsune's own embedding subsystem (Arctic
  Embed M v2.0, ONNX, CPU) is sufficient for now.
- Log/diagnostics streaming Sidecar → backend.
- Rate limits, token quotas, usage accounting, time-window
  restrictions.
- User-level restrictions spanning multiple API-keys of one consumer.
- LM Studio, vLLM, llama.cpp sidecar adapters (the *protocol* is
  designed for them from day one; the *implementations* follow).
- Multi-sidecar-per-homelab bundles, load balancing, failover.

### Non-goals — permanent

- Model pulls driven by the consumer. Model management is always and
  forever the host's local responsibility.
- Discovery: no "browse public homelabs" UI, no listing API, no
  search. Sharing is strictly out-of-band (Alice DMs Bob her
  Homelab-ID and API-key).
- Batch-mode inference. Chatsune is a streaming-first conversational
  product.
- Sidecar-to-sidecar communication or peer-to-peer topologies.

---

## 3. Architecture Overview

```
                                ┌────────────────────────────────┐
                                │   Chatsune Backend (cloud)     │
                                │                                │
┌────────────┐  REST            │  ┌──────────────────────────┐  │
│  Host UI   │  /api/llm/       │  │ Community Provisioning   │  │
│ (Alice)    │─┤ homelabs/...   │──▶│   • homelabs             │  │
└────────────┘                  │  │   • api_keys             │  │
                                │  └──────────────────────────┘  │
┌────────────┐                  │  ┌──────────────────────────┐  │
│ Consumer UI│──▶ community     │  │  CommunityAdapter        │  │
│ (Bob)      │    Connection    │  │   (backend/modules/llm)  │  │
└────────────┘                  │  └────────────┬─────────────┘  │
                                │               │                │
                                │  ┌────────────▼─────────────┐  │
                                │  │  SidecarRegistry         │  │
                                │  │   (in-process)           │  │
                                │  │   homelab_id → CSP conn  │  │
                                │  └────────────┬─────────────┘  │
                                └───────────────│────────────────┘
                                                │
                                     wss:// + cshost_... (CSP/1)
                                                │
                                    ┌───────────▼───────────┐
                                    │   Chatsune Sidecar    │
                                    │   (Alice's home box)  │
                                    │                       │
                                    │   • CSP translator    │
                                    │   • Engine adapter    │
                                    └───────────┬───────────┘
                                                │
                                                │  HTTP (localhost)
                                                │
                                    ┌───────────▼───────────┐
                                    │  Ollama / LM Studio / │
                                    │  vLLM / llama.cpp     │
                                    └───────────────────────┘
```

**Key invariants:**

- The backend and the sidecar speak **only CSP** to each other. No
  Ollama-API, no OpenAI-API across this boundary.
- The backend never originates outbound to the host's network; the
  sidecar always initiates. This is what makes CGNAT/dynamic-IP hosts
  work at all.
- One sidecar = one homelab = one engine. Alice running Ollama and LM
  Studio on the same box runs two sidecars.
- The `community` adapter does not know which engine is upstream and
  does not care. That is the sidecar's problem.

**Engine-agnostic boundary — hard rule.**

Whatever the host is running — Ollama, LM Studio, vLLM, llama.cpp,
or something not yet supported — **the API surface from the Chatsune
backend's perspective MUST be identical.** The `community` adapter
and the `SidecarRegistry` must never contain a code path that
branches on `engine.type`, `engine.version`, or
`engine_family`. Requesting `generate_chat` against a Wohnzimmer-
Ollama sidecar and a Strix-LM-Studio sidecar goes through the
exact same backend code. The only permitted consumers of
`engine.type` and `engine.version` are:

- diagnostics output (the "powered by Ollama 0.5.0" subtitle in the
  Connection details panel),
- structured log lines for operator visibility,
- the test-button's response payload.

Any feature that *appears* to require branching on engine type is a
symptom of a missing field in CSP and must be solved by extending
the protocol (a new capability flag, a new option), **not** by
leaking engine identity into backend logic. This rule is what lets
new sidecar implementations (LM Studio, vLLM, llama.cpp) be shipped
without touching the Chatsune backend at all.

---

## 4. Data Model

### 4.1 Tokens

Three distinct tokens, each with its own purpose, shape, and
lifecycle.

| Token | Shape | Prefix | Length | Secret? | Generation |
|---|---|---|---|---|---|
| **Host-Key** | `cshost_` + URL-safe base64 | `cshost_` | 50 chars total | Yes | `secrets.token_urlsafe(32)` |
| **API-Key** | `csapi_` + URL-safe base64 | `csapi_` | 49 chars total | Yes | `secrets.token_urlsafe(32)` |
| **Homelab-ID** | URL-safe base64, no prefix | — | 11 chars | No | `secrets.token_urlsafe(8)` |

The `cs*_` prefixes exist for two reasons: (a) a host glancing at their
`.env` immediately knows which token they are looking at, and (b)
public secret-scanners (GitHub, GitGuardian) can hit the prefix with a
deterministic regex if a host accidentally commits one.

**Storage.** Host-Keys and API-Keys are stored only as `SHA-256`
hashes plus a four-character "hint" (the last four chars of the
plaintext, used in UI listings so the host can recognise which key
they mean). SHA-256 — not argon2id — is the right primitive here
because these tokens carry 256 bits of random entropy, so the slow-
hash argument (which exists to frustrate brute-force attacks on
low-entropy passwords) does not apply, and we validate keys on
every inference request where fast lookups matter. Per OWASP's API-
key cheat sheet a single SHA-256 pass is sufficient for high-
entropy tokens.

The plaintext is shown exactly **once** — at creation time — and
never again. The Homelab-ID is stored in plaintext; it is not a
secret.

**Rotation.**

- Host-Key: revoke + regenerate. Active sidecar connection receives
  an `auth_revoked` frame and disconnects.
- API-Key: revoke + regenerate. Consumer must update their Connection
  with the new key. Any in-flight request on that key completes;
  subsequent requests fail fast.
- Homelab-ID: **not rotatable.** Deleting the homelab and creating a
  new one is the only way to get a fresh ID; this cleanly cascades
  (all API-keys revoked, all consumers' Connections become unusable,
  which is the intended, legible outcome).

### 4.2 MongoDB Collections

Both collections are created lazily (no migration needed — per the
2026-04-15 beta policy we still add new collections freely; only
*renames/removals of existing fields* require a migration).

#### `llm_homelabs`

```python
{
  "_id": ObjectId,
  "user_id": str,                    # owning host
  "homelab_id": str,                 # 11 chars, unique globally
  "display_name": str,               # "Wohnzimmer-GPU", editable
  "host_key_hash": str,              # sha256(plaintext), hex
  "host_key_hint": str,              # last 4 chars of plaintext
  "status": Literal["active", "revoked"],
  "created_at": datetime,
  "last_seen_at": datetime | None,
  "last_sidecar_version": str | None,
  "last_engine_info": {              # populated from most recent handshake
    "type": str,                     # "ollama" | "lmstudio" | "vllm" | "llamacpp"
    "version": str | None,
  } | None,
}
```

Indexes:
- Unique on `homelab_id`.
- Unique on `host_key_hash`.
- Compound on `(user_id, created_at)` for listing.

#### `llm_homelab_api_keys`

```python
{
  "_id": ObjectId,
  "homelab_id": str,                 # parent homelab
  "user_id": str,                    # host (denormalised for access-control checks)
  "api_key_id": str,                 # short opaque id for UI/event payloads
  "display_name": str,               # "Bob (Testphase)"
  "api_key_hash": str,               # sha256(plaintext), hex
  "api_key_hint": str,
  "allowed_model_slugs": list[str],  # explicit whitelist; empty = no access
  "status": Literal["active", "revoked"],
  "created_at": datetime,
  "revoked_at": datetime | None,
  "last_used_at": datetime | None,
}
```

Indexes:
- Unique on `api_key_hash`.
- Compound on `(homelab_id, created_at)` for listing.

**Allowlist semantics (v1, strict).**

- Default on creation: `[]` — nothing accessible. Host must tick
  models explicitly. Safer default; matches the real-world pattern
  where the host wants to offer *one specific* model.
- No wildcards, no "all models" marker. Explicit slugs only.
- New model appears on sidecar: each API-key must be edited
  explicitly. No auto-inclusion, no nudge UI, no hand-holding. Hosting
  compute is a prosumer activity.
- Model disappears from sidecar: the allowlist entry stays. The
  model simply stops appearing in the consumer's model picker. If it
  returns, access resumes automatically. No cleanup.

### 4.3 Consumer-Side (reuses existing `llm_connections`)

A consumer creates a normal Connection of `adapter_type =
"community"`. No new collection is needed. The Connection config
carries:

```python
{
  "homelab_id": str,        # plain, pasted from host
  "api_key": str,           # encrypted at rest (secret_fields)
}
```

Model unique IDs follow INS-019: `<connection_slug>:<model_slug>` —
the consumer chooses the slug ("alices-gpu"), so ids look like
`alices-gpu:llama3.2:8b`. The homelab's host-side `display_name`
("Wohnzimmer-GPU") is surfaced in the Connection details panel as a
provenance subtitle, but does **not** participate in the unique-id
composition. That keeps the consumer in control of their own slug
namespace while still giving them a legible "provided by" badge.

---

## 5. Chatsune Sidecar Protocol v1 (CSP/1)

### 5.1 Transport

- WebSocket Secure (`wss://`) to `/ws/sidecar` on the Chatsune
  backend.
- The sidecar is always the initiator. The backend never dials out.
- Authentication: `Authorization: Bearer cshost_...` header on the
  upgrade request. JWT is not accepted on this endpoint.
- TLS is terminated by the Chatsune reverse proxy as usual. The
  sidecar verifies the backend certificate; no self-signed shortcuts.
- All frames are JSON text frames. Binary frames are reserved for
  future use (e.g. embeddings, image returns).

### 5.2 Frame Envelope

Every frame has a `type` field. Frames that belong to an operation
carry an `id` (UUID, chosen by the initiating side).

```json
{ "type": "<frame-type>", "id": "<uuid|null>", ... }
```

### 5.3 Frame Catalogue

**Connection lifecycle**

| Type | Direction | Purpose |
|---|---|---|
| `handshake` | sidecar → backend | First frame; declares versions, engine, caps. |
| `handshake_ack` | backend → sidecar | Accepts or rejects the handshake. |
| `ping` / `pong` | either | Keepalive. |
| `auth_revoked` | backend → sidecar | Host-Key was revoked; disconnect. |
| `superseded` | backend → sidecar | A newer sidecar with the same host-key connected; this one must exit. |

**Request/response within a connection**

| Type | Direction | Purpose |
|---|---|---|
| `req` | backend → sidecar | Start an operation (`op` = `list_models` \| `generate_chat`). |
| `res` | sidecar → backend | Final non-streaming response to a `req`. |
| `stream` | sidecar → backend | Intermediate streaming chunk for an in-flight `req`. |
| `stream_end` | sidecar → backend | Terminal frame for a streamed `req`; carries `finish_reason` + `usage`. |
| `err` | sidecar → backend | Error within a specific `req`. |
| `cancel` | backend → sidecar | Abort an in-flight `req`. |

### 5.4 Handshake

Sidecar sends, immediately after connect:

```json
{
  "type": "handshake",
  "csp_version": "1.0",
  "sidecar_version": "1.0.0",
  "engine": {
    "type": "ollama",
    "version": "0.5.0",
    "endpoint_hint": "http://localhost:11434"
  },
  "max_concurrent_requests": 2,
  "capabilities": ["chat_streaming", "tool_calls", "vision", "reasoning"]
}
```

Backend replies:

```json
{
  "type": "handshake_ack",
  "csp_version": "1.0",
  "homelab_id": "Xk7bQ2eJn9m",
  "display_name": "Wohnzimmer-GPU",
  "accepted": true,
  "notices": []
}
```

**Version negotiation.** Major version must match exactly. Minor
mismatches: both sides downgrade to `min(sidecar, backend)`. On major
mismatch the backend sends `accepted: false` with a `notices` entry
explaining the required version, and closes the socket.

**Capabilities.** The set is declared per-sidecar and carried in the
backend's in-memory `SidecarRegistry`. The `community` adapter
consults capabilities when translating a `CompletionRequest` to
decide whether to, for example, pass through tool definitions or
refuse the request if tools are required but unavailable.

### 5.5 `list_models`

Backend → sidecar:

```json
{ "type": "req", "id": "<uuid>", "op": "list_models" }
```

Sidecar → backend:

```json
{
  "type": "res",
  "id": "<uuid>",
  "ok": true,
  "body": {
    "models": [
      {
        "slug": "llama3.2:8b",
        "display_name": "Llama 3.2 8B Instruct",
        "parameter_count": 8030261248,
        "context_length": 131072,
        "quantisation": "Q4_K_M",
        "capabilities": ["text", "tool_calling", "vision"],
        "engine_family": "ollama",
        "engine_model_id": "llama3.2:8b",
        "engine_metadata": { ... }
      }
    ]
  }
}
```

`capabilities` is a subset of `{"text", "tool_calling", "vision",
"reasoning", "json_mode"}`. `engine_metadata` is free-form and
opaque to the backend; it exists so the sidecar can expose engine-
specific hints (e.g. Ollama's `family`, `quantization_level`, etc.)
without the protocol needing a new field every release.

The backend caches the result in Redis per Connection (30-min TTL,
INS-001 semantics). No push-on-change — next cache miss refetches.

**Engines without rich metadata.** llama.cpp's `server` exposes
almost nothing beyond model name. The sidecar is expected to fill
missing fields by combining engine output with a local lookup table
(e.g. GGUF inspection). Models for which `context_length` cannot be
determined **must be omitted** from the list, mirroring the
`ollama_http` adapter's behaviour (INS-019) — a model whose context
window is unknown cannot be safely offered.

### 5.6 `generate_chat`

Backend → sidecar:

```json
{
  "type": "req",
  "id": "<uuid>",
  "op": "generate_chat",
  "body": {
    "model_slug": "llama3.2:8b",
    "messages": [
      { "role": "system", "content": "..." },
      { "role": "user", "content": [
        { "type": "text", "text": "..." },
        { "type": "image", "media_type": "image/png", "data_b64": "..." }
      ]},
      { "role": "assistant", "content": "...", "tool_calls": [...] },
      { "role": "tool", "content": "...", "tool_call_id": "..." }
    ],
    "tools": [ ... ],
    "parameters": {
      "temperature": 0.7,
      "top_p": 0.9,
      "max_tokens": 4096,
      "stop": ["..."]
    },
    "options": {
      "reasoning": true
    }
  }
}
```

The message/tool/parameter shape is deliberately a **superset of
OpenAI's chat-completions schema** — any engine whose wire format is
OpenAI-compatible (LM Studio, vLLM, llama.cpp-server) translates
trivially; Ollama's slightly divergent shape is handled inside the
Ollama sidecar. Keeping the protocol OpenAI-shaped at the boundary
means new engine adapters are straightforward to write.

Sidecar streams `stream` frames:

```json
{
  "type": "stream",
  "id": "<uuid>",
  "delta": {
    "content": "Hel",
    "reasoning": null,
    "tool_calls": null
  }
}
```

Only one of `content` / `reasoning` / `tool_calls` is populated per
frame; the others are `null` or omitted. Reasoning is a **separate
channel** to match how Ollama and DeepSeek-R1 style models emit
`<think>` blocks distinct from the main content — the Chatsune
frontend renders them in a collapsible "thinking" panel, so they
cannot be concatenated with normal content on the wire.

Tool-call fragments:

```json
{
  "type": "stream",
  "id": "<uuid>",
  "delta": {
    "tool_calls": [
      {
        "index": 0,
        "id": "call_abc123",
        "function": { "name": "get_weather", "arguments": "{\"loc" }
      }
    ]
  }
}
```

Fragments accumulate by `index` following OpenAI semantics — the
consumer assembles the final call by concatenating `arguments`
fragments.

Terminal frame:

```json
{
  "type": "stream_end",
  "id": "<uuid>",
  "finish_reason": "stop",
  "usage": {
    "prompt_tokens": 123,
    "completion_tokens": 456,
    "total_tokens": 579
  }
}
```

Valid `finish_reason` values: `stop`, `length`, `tool_calls`,
`cancelled`, `error`. On `error`, the preceding frame will be an
`err` and `usage` is best-effort (may be absent).

### 5.7 Cancellation

The consumer aborts a stream (closes the SSE, navigates away, clicks
Stop). The `community` adapter:

1. Sends `{ "type": "cancel", "id": "<uuid>" }` to the sidecar.
2. Stops forwarding further `stream` frames to its caller.
3. Waits for the sidecar's terminal `stream_end` with
   `finish_reason: "cancelled"` before releasing the request's
   semaphore slot.

The sidecar:

1. Calls its engine's abort/cancel endpoint (Ollama: close HTTP
   stream; OpenAI-compatible: close HTTP stream; llama.cpp:
   `POST /completion` has no native cancel — sidecar closes the
   HTTP connection, which server.cpp respects).
2. Emits `stream_end` with `finish_reason: "cancelled"`.

Best-effort semantics — an engine that does not honour cancel may
continue a short time. The backend treats the request slot as
released as soon as `stream_end` arrives, regardless of what the GPU
is still doing.

### 5.8 Errors

```json
{
  "type": "err",
  "id": "<uuid>",
  "code": "model_not_found",
  "message": "Model not available on this homelab.",
  "detail": null,
  "recoverable": false
}
```

Canonical error codes:

| Code | Meaning |
|---|---|
| `model_not_found` | Model is not in the sidecar's current list. |
| `model_oom` | Engine could not load the model (typically VRAM). |
| `engine_unavailable` | Sidecar cannot reach its local engine. |
| `engine_error` | Engine returned a non-success response. |
| `invalid_request` | Request shape rejected (bad image, bad param). |
| `rate_limited` | Sidecar's declared concurrency cap exceeded mid-flight (rare; usually prevented by the backend's semaphore). |
| `cancelled` | Mirrors `stream_end.finish_reason`; emitted for non-streaming ops. |
| `internal` | Anything else. Always `recoverable: false`. |

The `message` field is user-safe and may be surfaced as-is. `detail`
is for backend logs only and MUST NOT be shown in the Chatsune UI.

### 5.9 Heartbeat

- Sidecar sends `{"type": "ping"}` every 30 s.
- Backend replies `{"type": "pong"}` within 10 s.
- Two missed pongs (> 60 s) → sidecar reconnects.
- Backend detects two missed pings (> 90 s) → marks the homelab's
  connection state `degraded`; > 5 min → `offline`.

The UI flips the Connection's "live" badge accordingly.

### 5.10 Reconnect

Sidecar reconnects with exponential backoff, capped:

```
1s → 2s → 4s → 8s → 16s → 32s → 60s (cap, steady state)
```

Jitter: ±25 % on each delay to avoid thundering herd when the
backend restarts. Any successful handshake resets the backoff.

Backend tolerates short outages silently. In-flight requests at the
moment of disconnect fail immediately with `err / engine_unavailable`
— they are not queued across reconnects. The consumer UI surfaces the
error; the user retries manually.

---

## 6. Community Adapter (Consumer Side)

A new adapter in `backend/modules/llm/_adapters/_community.py`
registered in `backend/modules/llm/_registry.py` alongside
`ollama_http`.

**Class attributes:**

- `adapter_type = "community"`
- `display_name = "Community"`
- `view_id = "community"`
- `secret_fields = frozenset({"api_key"})`

**`config_schema`:** two fields, both required.

- `homelab_id` — 11-char string, pasteable. UI shows `homelab://` as a
  hardcoded prefix label so the user pastes only the ID.
- `api_key` — secret, validated by prefix `csapi_`.

**`templates()`:** one template "Homelab via Community", with
placeholders; no other presets (there are no "well-known" homelabs).

**`fetch_models`:** looks up the resolved homelab from the
`SidecarRegistry`. If offline, returns `[]` and the Connection
appears empty in the model picker. If online, sends a `list_models`
request, awaits the `res`, filters the model list by the API-key's
`allowed_model_slugs`, and returns the filtered result.

**`stream_completion`:** translates the backend's
`CompletionRequest` into a CSP `generate_chat` request, forwards the
streaming frames as `ProviderStreamEvent`s, and handles cancellation
+ terminal events. Reasoning-channel frames map to the existing
"thinking" stream event type; content frames map to normal deltas;
tool-call frames map to the existing tool-call delta event.

**`router()`:** exposes two endpoints under the generic
`/api/llm/connections/{id}/adapter/` prefix:

- `POST /test` — issues `list_models` via the live sidecar
  connection, returns `{ valid: bool, latency_ms: int, model_count:
  int, error: str | None }`. No completion is attempted — no tokens
  are consumed, no model is loaded.
- `GET /diagnostics` — returns the most recent handshake's `engine`
  info, `sidecar_version`, `capabilities`, and last-seen timestamps.

**Concurrency.** Per-Connection `max_parallel` (INS-017) still
applies on the consumer side. On the host side, the sidecar-declared
`max_concurrent_requests` from the handshake is enforced by the
backend's `SidecarRegistry` before dispatch: excess requests wait on
a homelab-scoped semaphore. The effective cap is
`min(per_connection_max_parallel, sidecar_max_concurrent_requests)`.

**Access check.** On every request the `community` adapter verifies:

1. The resolved Connection's stored `homelab_id` matches a homelab
   with `status = "active"`.
2. The plaintext `api_key` (looked up from the encrypted config)
   hashes to an `api_key_hash` on that homelab, with `status =
   "active"`.
3. The requested `model_slug` appears in that API-key's
   `allowed_model_slugs`.

Failure at any step maps to a `StreamRefused` terminal event with a
user-safe message. Attempts are **not logged to MongoDB** in v1 —
that goes with usage logging in v2.

---

## 7. Host-Side UI: Community Provisioning

A new top-level section under Settings, clearly distinct from
Connections. Visual tone follows the **opulent prototype style**
(consistent with other user-facing screens).

### 7.1 Empty State

Large card: "Share your home compute with people you invite. Run the
Chatsune Sidecar on your GPU box, point it at this backend with the
Host-Key you will generate here, and issue API-Keys to the people you
want to share with." Primary button: **Create Homelab**.

### 7.2 Homelab List

One card per homelab:

- Display name (editable inline).
- Homelab-ID (monospace, copy button).
- Host-Key hint ("…9f2a") + "Regenerate" button.
- Live status: `online` / `degraded` / `offline`, last-seen relative
  time.
- Last-seen engine + sidecar version, once known.
- Actions: **Manage API-Keys**, **Delete**.

### 7.3 Create / Regenerate Host-Key

Modal, one-shot plaintext display. Copy-to-clipboard + a prominent
notice: "This key will not be shown again. Put it into your
sidecar's `.env` under `CHATSUNE_HOST_KEY=` before you close this
dialog." Secondary download-as-`.env`-snippet option.

### 7.4 API-Keys Sub-View

Table per homelab:

- Display name (inline editable).
- Key hint ("…t7k9").
- Allowed models: a count + small chip list, click to edit.
- Created, last-used.
- Actions: **Regenerate**, **Revoke**.

**Allowlist editor.** Modal with the current model list fetched from
the homelab. Checkboxes per model. Saving writes the slug list. If
the homelab is offline the modal shows the last-known list with a
warning banner; models may exist that aren't shown and vice versa.

**Create API-Key wizard.** Two steps: name + (optional) model
pre-selection. On submit the plaintext key is displayed once, same
one-shot pattern as the Host-Key. No "Create for myself" button, no
convenience autofill — the host picks models explicitly every time.

### 7.5 Events the UI Reacts To

- `llm.homelab.created`
- `llm.homelab.updated`
- `llm.homelab.deleted`
- `llm.homelab.host_key_regenerated`
- `llm.homelab.status_changed` (`online` / `degraded` / `offline`)
- `llm.homelab.last_seen` (periodic, coarse; throttled)
- `llm.api_key.created`
- `llm.api_key.updated`
- `llm.api_key.revoked`

All events target `[user_id]` (the host). The plaintext keys are
*never* in events — they are only in the REST response body at the
moment of creation.

---

## 8. Security Considerations

| Risk | Mitigation |
|---|---|
| Host-Key or API-Key leak | SHA-256-hashed at rest (OWASP-sanctioned for high-entropy tokens); shown once at creation; revocable; prefix enables secret-scanner detection on public repos. |
| Sidecar impersonation | Reverse-only transport; only the holder of the plaintext Host-Key can establish the WSS session. |
| Lateral abuse (sidecar probes non-LLM APIs) | `/ws/sidecar` is isolated. The sidecar connection has no fan-out of the user event stream, no REST access, no route to another user's data. Only CSP ops are served. |
| Duplicate sidecars per homelab | Last-wins: the new connect closes the old connection with a `superseded` frame; a `llm.homelab.status_changed` fires. |
| Malicious inference response | Sidecar output is treated exactly like any other upstream — it lands in the consumer's own session with no trust elevation. |
| Consumer-targeted DoS by rogue host | Host can revoke keys and shut down their sidecar at any time. Consumer rate-limits on the frontend remain as before. |
| Homelab-ID enumeration | 64-bit random IDs plus per-IP rate-limits on unauthenticated handshake failures make enumeration impractical. Even a guessed ID requires a valid API-key to use. |
| Model allowlist bypass | Every request re-validates the allowlist on the server side. The frontend model list is purely advisory; the backend does not trust it. |
| Cross-user leakage through shared sidecar | API-keys are scoped per-homelab and the host authored every one. If a host knowingly gives the same API-key to two consumers, that is their explicit choice; there is no cross-host key sharing. |

---

## 9. Backend Surface

### 9.1 New Topics (`shared/topics.py`)

```
LLM_HOMELAB_CREATED                  = "llm.homelab.created"
LLM_HOMELAB_UPDATED                  = "llm.homelab.updated"
LLM_HOMELAB_DELETED                  = "llm.homelab.deleted"
LLM_HOMELAB_HOST_KEY_REGENERATED     = "llm.homelab.host_key_regenerated"
LLM_HOMELAB_STATUS_CHANGED           = "llm.homelab.status_changed"
LLM_HOMELAB_LAST_SEEN                = "llm.homelab.last_seen"
LLM_API_KEY_CREATED                  = "llm.api_key.created"
LLM_API_KEY_UPDATED                  = "llm.api_key.updated"
LLM_API_KEY_REVOKED                  = "llm.api_key.revoked"
```

### 9.2 New DTOs (`shared/dtos/llm.py`)

- `HomelabDto` — homelab without any key material.
- `HomelabCreatedDto` — includes the one-time plaintext Host-Key.
- `HomelabHostKeyRegeneratedDto` — includes the one-time plaintext new Host-Key.
- `ApiKeyDto` — api-key without the plaintext.
- `ApiKeyCreatedDto` — includes the one-time plaintext API-Key.
- `HomelabStatusDto` — status + last-seen + engine info.

Plaintext keys appear **only** in the REST response body, never in
events. This is the one place in Chatsune's DTO layer where a
"create response" legitimately diverges from the steady-state DTO.

### 9.3 New Event Classes (`shared/events/llm.py`)

Five to match the topics above. Homelab events carry `HomelabDto`
(no plaintext). API-key events carry `ApiKeyDto` (no plaintext).
`HomelabHostKeyRegeneratedEvent` and its API-key analogue carry only
the hint — the new plaintext is returned via the REST response only.

### 9.4 New REST Endpoints (LLM module)

```
POST   /api/llm/homelabs                         → HomelabCreatedDto (plaintext host-key)
GET    /api/llm/homelabs                         → list[HomelabDto]
GET    /api/llm/homelabs/{id}                    → HomelabDto
PATCH  /api/llm/homelabs/{id}                    → HomelabDto          (rename)
DELETE /api/llm/homelabs/{id}                    → 204
POST   /api/llm/homelabs/{id}/regenerate-host-key
                                                 → HomelabHostKeyRegeneratedDto

POST   /api/llm/homelabs/{id}/api-keys           → ApiKeyCreatedDto
GET    /api/llm/homelabs/{id}/api-keys           → list[ApiKeyDto]
PATCH  /api/llm/homelabs/{id}/api-keys/{key_id}  → ApiKeyDto           (rename or edit allowlist)
DELETE /api/llm/homelabs/{id}/api-keys/{key_id}  → 204
POST   /api/llm/homelabs/{id}/api-keys/{key_id}/regenerate
                                                 → ApiKeyCreatedDto
```

All endpoints resolve the host user from the JWT and verify
ownership of the homelab. A sanity cap of 10 homelabs and 50
API-keys per user applies in v1.

### 9.5 New WebSocket Endpoint

`/ws/sidecar` — Host-Key-authenticated, CSP/1 traffic only. No fan-
out of user events, no REST access. Implemented in `backend/ws/`
alongside the existing `/ws` endpoint but entirely separate in terms
of authentication, routing, and routed scopes.

### 9.6 In-Memory State

A process-local `SidecarRegistry` in `backend/modules/llm/` maps
`homelab_id` → connection object (per-request inbox/outbox queues,
pending-request table, capability set, semaphore for the declared
`max_concurrent_requests`). Cleared on process restart.

### 9.7 Event Bus Fan-out Rules (`backend/ws/event_bus.py`)

All `llm.homelab.*` and `llm.api_key.*` events target `[user_id]`
only (the host). No cross-user visibility.

---

## 10. Migration & Compatibility

- The old `ollama_homelab` adapter referenced in ADR-001 is **not
  implemented** in production, so there is nothing to migrate from
  the consumer side.
- New collections (`llm_homelabs`, `llm_homelab_api_keys`) are
  created lazily. No explicit migration script is required under the
  2026-04-15 beta policy.
- The `ollama_http` adapter is unaffected. Users with existing Ollama
  Cloud or self-hosted-LAN Connections continue as before.
- Mark `docs/adr-001-homelab-sidecar.md` as `Status: Superseded by
  docs/superpowers/specs/2026-04-16-community-provisioning-design.md`
  on merge.

---

## 11. Sidecar Specification (out of scope for this repo's implementation)

The reference sidecar is **not built inside this repository and not
inside the implementation plans that follow this spec.** It will be
developed in a dedicated repository in a separate Claude Code
session, keeping working directories and review cycles cleanly
isolated.

What **is** in scope here is authoring a **sidecar specification
document** — a self-contained spec that the sidecar-repo session can
consume as its own primary input without needing to read this entire
design. It lives at
`docs/superpowers/specs/2026-04-16-chatsune-sidecar-spec.md` and
covers:

- CSP/1 wire format (copied/extracted from §5 of this document —
  canonical, not a summary).
- Required behaviour: connect, handshake, frame loop, cancel,
  reconnect, healthcheck, zero persistent state.
- Required environment variables: `CHATSUNE_BACKEND_URL` (wss),
  `CHATSUNE_HOST_KEY`, and engine-specific URLs (`OLLAMA_URL`,
  `LMSTUDIO_URL`, `VLLM_URL`, `LLAMACPP_URL` — only the ones the
  specific sidecar binary consumes).
- Engine translation expectations: how each supported engine's chat-
  completion shape maps to CSP `generate_chat`, how streaming
  responses map back, where reasoning content is separated, how
  tool-call fragments are reconstructed from engine output.
- Metadata-gap handling: engines without rich model metadata (notably
  llama.cpp) must fill `context_length` via GGUF inspection or a
  local lookup table; models for which this cannot be determined
  must be dropped from the list (mirrors INS-019 for `ollama_http`).
- Healthcheck, logging, container/image conventions, release
  cadence expectations.
- Backward/forward compatibility rules — CSP-major-version rules
  from §5.4.

**Versioning of the spec document itself.** The sidecar spec is
versioned in lockstep with CSP — any CSP/2 work produces a new
sidecar spec revision alongside the protocol change.

**Reference image (built in the sidecar repo, not here):**
`ghcr.io/<org>/chatsune-sidecar-ollama:1.0.0` plus `:latest`, GPL-3.0
licence, README with `compose.yml` snippet and `.env.example`. Those
deliverables are tracked in the sidecar repo's own planning.

---

## 12. Open Items for Implementation

Not blockers for shipping, but each needs a short follow-up during
implementation:

- **Per-IP handshake rate limiting** on `/ws/sidecar` to blunt any
  Host-Key brute-force attempts. Target: 10 failed handshakes per IP
  per minute → 1-hour block.
- **Concrete wording** for every user-facing notice around one-shot
  plaintext keys (Host-Key, API-Key). Consistency with existing
  "sensitive action" modal tone.
- **Observability surface**: structured log lines on every CSP
  transition (connect, handshake, request start/end, error, cancel,
  disconnect), tagged with `homelab_id`, `csp_request_id`, and the
  existing Chatsune correlation id. Sticking to claude-oriented
  logging conventions (CLAUDE.md §Claude-Oriented Logging).
- **`llm_harness` coverage**: extend or add a sibling harness that
  can drive the CSP side of a sidecar for local repro of protocol
  issues, analogous to how `llm_harness` drives Ollama Cloud today.
- **Metric placeholders** (request count per homelab, RTT, concurrent
  in-flight, reconnect count) exposed as log fields for now; full
  dashboarding is deferred to whenever Chatsune adds a metrics
  pipeline.

---

## 13. Consequences

**Positive.** A genuinely new capability: cloud-hosted Chatsune
instances can use their users' private home GPUs, preserving the
BYOK model (INS-002) without any external tunnel or port-forwarding
dependency, and — uniquely — the same mechanism lets users share
their home compute with invited friends. The protocol is engine-
agnostic from day one, so LM Studio, vLLM, and llama.cpp sidecars are
"new implementations of the same wire format" rather than new
protocols. Model unique ids (INS-019), the connections model
(INS-016), and per-connection concurrency (INS-017) all extend
naturally to this adapter.

**Negative.** The backend grows a second WebSocket endpoint with its
own auth story and its own in-memory registry. The CSP/1 protocol is
an API surface that must be versioned carefully — breaking changes
mean operators must upgrade sidecars. The Community Provisioning UI
is a non-trivial new settings screen.

**Reversible?** Largely yes. The collections, REST endpoints,
WebSocket endpoint, adapter, and UI can all be removed without
affecting any other module (module-boundary rule, CLAUDE.md §1). Any
sidecars running in the wild become inert the moment the backend
endpoint returns 404; no further action is required.
