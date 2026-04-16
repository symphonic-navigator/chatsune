# Chatsune Sidecar Specification (CSP/1)

**Status:** Draft (2026-04-16)
**Audience:** Implementers of a Chatsune sidecar — the process that runs
next to a local LLM engine (Ollama, LM Studio, vLLM, llama.cpp) and
bridges it to a remote Chatsune backend.
**Parent design:** `docs/superpowers/specs/2026-04-16-community-provisioning-design.md`
in the Chatsune backend repo. This sidecar specification is
intentionally self-contained so that an implementer can work from this
document alone.

---

## 1. Purpose

A Chatsune sidecar exposes a local inference engine to a Chatsune
backend running somewhere else on the internet — typically a cloud VPS
that cannot reach the host box (CGNAT, dynamic IP, no port-forwarding,
intermittent uptime). The sidecar initiates an outbound WebSocket
Secure connection to the backend, identifies itself with a Host-Key,
and thereafter serves inference requests that the backend sends down
that same connection.

A sidecar is **one engine, one homelab, one process**. Do not multi-
plex engines in a single sidecar process. If the host runs Ollama and
LM Studio side by side, they run two sidecars with two Host-Keys.

---

## 2. Scope

### This specification covers

- The wire format of Chatsune Sidecar Protocol version 1 (CSP/1).
- Required behaviour: connect, authenticate, handshake, heartbeat,
  frame loop, cancellation, reconnect, healthcheck, clean shutdown.
- Environment variables, container conventions, logging expectations.
- Engine translation expectations per supported engine (§6).
- Metadata gap handling (§6.5).

### This specification does not cover

- The Chatsune backend side of the protocol (see parent design).
- How a host installs, registers, or configures a sidecar within the
  Chatsune UI.
- Any authentication other than the Host-Key bearer header.
- Any transport other than WebSocket Secure over TLS.
- Any operation other than `list_models` and `generate_chat` (v1
  intentionally ships only these — see §5.3).

---

## 3. Transport

- **Protocol:** WebSocket Secure (`wss://`). TCP + TLS + WS.
- **Initiator:** The sidecar always initiates. The backend never
  dials out to the sidecar.
- **Endpoint:** `wss://<backend-host>/ws/sidecar`.
- **TLS:** The sidecar MUST verify the backend's TLS certificate
  against the system trust store. No self-signed shortcuts, no
  `insecure` flags. If the operator deploys a Chatsune backend with
  a private CA, they install the CA into the sidecar's image.
- **Authentication:** `Authorization: Bearer cshost_<rest>` header
  on the WebSocket upgrade request. The `cshost_` prefix is
  mandatory — the backend rejects tokens without it. No JWT, no
  cookies, no query-string auth.
- **Frame type:** All application frames are JSON text frames. Binary
  frames are reserved for future CSP versions; v1 implementations
  MUST NOT send binary frames and MAY close the connection on
  receiving one.
- **Message size:** Frames up to 16 MiB MUST be supported (large
  multimodal payloads); beyond that the backend MAY close the
  connection.

---

## 4. Frame Envelope

Every frame is a single JSON object with a `type` string. Frames that
participate in a request/response cycle also carry an `id` (UUIDv4,
lowercase, hyphenated) chosen by the initiating side.

```json
{ "type": "<frame-type>", "id": "<uuid|null>", "...": "..." }
```

Unknown `type` values from the peer MUST be ignored (forward-
compatibility). Required fields missing from a recognised frame type
MUST terminate the connection with an error.

---

## 5. Frame Catalogue

### 5.1 Connection-lifecycle frames

| Type | Direction | Purpose |
|---|---|---|
| `handshake` | sidecar → backend | First frame after connect; declares versions, engine, capabilities. |
| `handshake_ack` | backend → sidecar | Accepts or rejects the handshake; carries the homelab's identity. |
| `ping` | either | Liveness probe. |
| `pong` | either | Response to ping. |
| `auth_revoked` | backend → sidecar | Host-Key was revoked by the host user. Sidecar MUST close cleanly and MUST NOT attempt to reconnect. |
| `superseded` | backend → sidecar | A newer sidecar connected with the same Host-Key. This sidecar MUST close cleanly and MUST NOT attempt to reconnect. |

### 5.2 Request/response frames

| Type | Direction | Purpose |
|---|---|---|
| `req` | backend → sidecar | Start an operation. Carries `op` (`list_models` or `generate_chat`). |
| `res` | sidecar → backend | Final non-streaming response to a `req`. |
| `stream` | sidecar → backend | Intermediate streaming chunk for an in-flight `req`. |
| `stream_end` | sidecar → backend | Terminal frame of a streamed `req`; carries `finish_reason` + `usage`. |
| `err` | sidecar → backend | Error for a specific `req`. Always paired with `stream_end` (for streaming ops) or stands alone (for non-streaming). |
| `cancel` | backend → sidecar | Abort an in-flight `req`. Sidecar MUST react and MUST eventually send `stream_end` with `finish_reason: "cancelled"`. |

### 5.3 v1 operations

Two, exactly:

- `list_models` — discovery.
- `generate_chat` — streaming chat completion.

Any other `op` value in a `req` MUST be answered with `err / code:
"invalid_request"`.

---

## 6. Handshake

Immediately after WebSocket open, the sidecar sends:

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

- `csp_version` — `"MAJOR.MINOR"` string. v1 sidecars send `"1.0"`.
- `sidecar_version` — semver of the sidecar build.
- `engine.type` — one of `"ollama"`, `"lmstudio"`, `"vllm"`,
  `"llamacpp"`. New values require a CSP minor-version bump.
- `engine.version` — free-form string; engine's reported version.
  Sidecar MUST make a best-effort query (e.g. Ollama's `GET /api/version`,
  llama.cpp-server's `GET /props`) and MAY emit `"unknown"`.
- `engine.endpoint_hint` — informational only; the backend logs it and
  does not use it.
- `max_concurrent_requests` — integer ≥ 1. The backend will never
  have more than this many in-flight `req`s open on this connection.
  Set it to match the engine's real capacity: Ollama with one model
  loaded = 1; vLLM with real batching = whatever the host sized for.
- `capabilities` — subset of `{"chat_streaming", "tool_calls",
  "vision", "reasoning"}`. Advertise only what the engine actually
  supports. `chat_streaming` is mandatory in v1.

The backend replies:

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

- `csp_version` — the **negotiated** version (see §6.1).
- `homelab_id` — the 11-char homelab identifier this sidecar is
  bound to. The sidecar MAY log this for operator reference.
- `display_name` — human-readable label from the host's UI. Also
  log-only.
- `accepted` — boolean. On `false` the backend will close the
  socket after this frame.
- `notices` — array of strings. Non-fatal warnings (e.g. "CSP/1.2
  capability `x` unsupported by backend, ignored"). The sidecar
  MAY log these.

### 6.1 Version negotiation

- **Major mismatch** → backend sends `accepted: false`, a `notices`
  entry describing the required version, closes the socket. The
  sidecar MUST NOT retry without an upgrade.
- **Minor mismatch** → both sides operate at `min(sidecar_minor,
  backend_minor)`. Sidecar MAY receive `notices` for any capability
  it advertised that the negotiated version does not support.
- **`accepted: false` for any other reason** → the sidecar MUST log
  the notices, close cleanly, and back off per §10. Common causes:
  Host-Key revoked just before connect, homelab deleted, incompatible
  engine.type on this backend version.

---

## 7. `list_models`

### 7.1 Request

```json
{ "type": "req", "id": "<uuid>", "op": "list_models" }
```

No body.

### 7.2 Response

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
        "engine_metadata": { }
      }
    ]
  }
}
```

- `slug` — **engine-local identifier**, what the user types in
  Ollama's CLI. MUST be unique within the list.
- `display_name` — human-readable. Falls back to `slug` if the
  engine offers no nicer name.
- `parameter_count` — integer or `null`. Count in parameters
  (not billions).
- `context_length` — integer. **Required, no `null` allowed.** If the
  sidecar cannot determine this value for a given model, it MUST
  drop that model from the response (see §6.5 — metadata gap
  handling).
- `quantisation` — string or `null`. Ollama/llama.cpp report values
  like `"Q4_K_M"`; other engines may report `null`.
- `capabilities` — subset of `{"text", "tool_calling", "vision",
  "reasoning", "json_mode"}`. Advertise only what the model truly
  supports; a consumer that asks for tool calling on a model that
  did not advertise it will get `err / invalid_request` at
  request time.
- `engine_family` — matches the handshake's `engine.type`.
- `engine_model_id` — the exact identifier the sidecar will pass
  back to its engine for this model. May equal `slug`; separated so
  engines with namespaced models stay legible.
- `engine_metadata` — free-form JSON object, opaque to the backend.
  Use it to expose engine-specific hints that Chatsune's UI or
  telemetry may surface later (e.g. Ollama's `family`,
  `format`, full `modelfile` hash).

### 7.3 Errors

If the engine is unreachable at request time, respond with `err`:

```json
{
  "type": "err",
  "id": "<uuid>",
  "code": "engine_unavailable",
  "message": "Ollama not reachable at http://localhost:11434.",
  "detail": "Connection refused",
  "recoverable": true
}
```

---

## 8. `generate_chat`

### 8.1 Request

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
      { "role": "assistant", "content": "...", "tool_calls": [
        {
          "id": "call_abc123",
          "type": "function",
          "function": { "name": "get_weather", "arguments": "{\"loc\":\"Vienna\"}" }
        }
      ]},
      { "role": "tool", "content": "...", "tool_call_id": "call_abc123" }
    ],
    "tools": [
      {
        "type": "function",
        "function": {
          "name": "get_weather",
          "description": "...",
          "parameters": { "...": "JSON-Schema" }
        }
      }
    ],
    "parameters": {
      "temperature": 0.7,
      "top_p": 0.9,
      "max_tokens": 4096,
      "stop": ["\n\n"]
    },
    "options": {
      "reasoning": true
    }
  }
}
```

**Message schema.**

- `role` — one of `"system"`, `"user"`, `"assistant"`, `"tool"`.
- `content` — either a string (text-only) or an array of content
  parts. Content parts have a `type` field:
  - `{"type": "text", "text": "..."}`
  - `{"type": "image", "media_type": "image/png|image/jpeg|...", "data_b64": "..."}`

  `system`, `tool`, and `assistant` messages are always plain
  strings. `user` messages MAY be arrays when multimodal.
- `tool_calls` (assistant only) — array of tool calls emitted by a
  previous model turn.
- `tool_call_id` (tool only) — matches the `id` of the tool call
  being responded to.

**Tools.** OpenAI-compatible tool definitions. Sidecars whose engine
does not natively support tool calling but whose advertised
capabilities omit `tool_calling` will never receive `tools` in a
request (the backend checks); if a sidecar does receive `tools`
against expectations, it MUST answer with `err / invalid_request`.

**Parameters.** All fields optional. Sidecar substitutes engine
defaults for anything absent.

**Options.**

- `reasoning` (default `false`) — when true, the sidecar MUST emit
  reasoning content on its own channel (§8.2) for models that
  separate thinking from final output. When false, reasoning-capable
  models MAY still produce thinking tokens; the sidecar MUST either
  suppress them or fold them into `content` — it MUST NOT split them
  across channels.

### 8.2 Streaming response

A `req` of op `generate_chat` is always streamed. The sidecar sends
zero or more `stream` frames, then exactly one terminal frame —
either `stream_end` (success or cancelled) or `err` followed by
`stream_end`.

**Content chunk:**

```json
{
  "type": "stream",
  "id": "<uuid>",
  "delta": {
    "content": "Hello",
    "reasoning": null,
    "tool_calls": null
  }
}
```

**Reasoning chunk (when `options.reasoning: true` and the model emits
thinking):**

```json
{
  "type": "stream",
  "id": "<uuid>",
  "delta": {
    "content": null,
    "reasoning": "Let me consider...",
    "tool_calls": null
  }
}
```

Reasoning is a **separate channel** from content. They MUST NOT be
concatenated on the wire. Ollama's `<think>...</think>` block must
be parsed by the sidecar and the inside emitted as `reasoning`
deltas; DeepSeek-R1's `reasoning_content` OpenAI-style field maps
directly.

**Tool-call chunk (OpenAI fragment semantics):**

```json
{
  "type": "stream",
  "id": "<uuid>",
  "delta": {
    "content": null,
    "reasoning": null,
    "tool_calls": [
      {
        "index": 0,
        "id": "call_abc123",
        "type": "function",
        "function": { "name": "get_weather", "arguments": "{\"loc" }
      }
    ]
  }
}
```

Fragments accumulate by `index`. The first fragment at a new index
SHOULD include `id`, `type`, and `function.name`; subsequent
fragments at the same index need only contain the next
`function.arguments` slice. The consumer assembles the full tool
call by concatenating `function.arguments` strings.

**Only one of `content` / `reasoning` / `tool_calls` is populated
per frame.** The other two are `null` or omitted. Do not send empty
deltas.

### 8.3 Terminal frame

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

Valid `finish_reason`:

| Value | Meaning |
|---|---|
| `stop` | Model reached a natural stopping point. |
| `length` | Hit `max_tokens` or the engine's context limit. |
| `tool_calls` | Model emitted tool calls and is awaiting tool results. |
| `cancelled` | Consumer cancelled; emit after handling `cancel`. |
| `error` | Preceded by an `err` frame. |

`usage` is best-effort. When the engine does not report token counts,
omit `usage` entirely (do not emit zeros).

---

## 9. Cancellation

```json
{ "type": "cancel", "id": "<uuid>" }
```

When the sidecar receives `cancel` for an in-flight `req`:

1. **Immediately** stop forwarding further engine output.
2. Signal the engine to abort the current generation. Engine-
   specific guidance:
   - **Ollama**: close the HTTP stream (Ollama respects this).
   - **OpenAI-compatible (LM Studio, vLLM)**: close the HTTP stream.
   - **llama.cpp server**: close the HTTP connection. `server.cpp`
     honours client disconnect.
3. Send `stream_end` with `finish_reason: "cancelled"`. `usage`
   MAY be omitted since partial tokens are not useful.

A `cancel` received for an unknown or already-terminated `id` MUST
be ignored silently (race: consumer cancelled at the same time as
the model finished).

Cancellation is best-effort — a model already deep into a long
generation on a slow backend may continue a short time. The backend
treats the slot as released as soon as `stream_end` arrives.

---

## 10. Errors

```json
{
  "type": "err",
  "id": "<uuid>",
  "code": "model_not_found",
  "message": "Model 'llama99' not available on this homelab.",
  "detail": null,
  "recoverable": false
}
```

| Code | Meaning | `recoverable` |
|---|---|---|
| `model_not_found` | Requested `model_slug` is not in the sidecar's current list. | `false` |
| `model_oom` | Engine could not load the model (usually VRAM exhaustion). | `true` |
| `engine_unavailable` | Sidecar cannot reach its local engine. | `true` |
| `engine_error` | Engine returned a non-success response. | engine-dependent |
| `invalid_request` | Request shape rejected — bad image encoding, malformed tools, unknown op. | `false` |
| `rate_limited` | Sidecar's own capacity exhausted mid-flight. Should be rare; normally prevented by the backend's concurrency control. | `true` |
| `cancelled` | Non-streaming op was cancelled. | `false` |
| `internal` | Anything else. | `false` |

`message` MUST be user-safe — it may be surfaced in the Chatsune UI
verbatim. `detail` is for operator logs only and MUST NOT contain
sensitive data (API keys, file system paths, internal hostnames).

For streaming ops (`generate_chat`), an `err` frame MUST be followed
by a `stream_end` with `finish_reason: "error"` — two frames, in
that order. For non-streaming ops (`list_models`), `err` stands
alone as the terminal response.

---

## 11. Heartbeat

- The sidecar sends `{"type":"ping"}` every **30 seconds**.
- The backend MUST reply with `{"type":"pong"}` within **10 seconds**.
- Two consecutive missed `pong`s (i.e. silence > 60 s) → the sidecar
  treats the connection as dead, closes it, and reconnects per §12.
- Either side MAY send `ping` at any time for its own liveness
  probe; the peer MUST reply promptly.

`ping` and `pong` carry no `id`.

---

## 12. Reconnect

On disconnect for any reason other than `auth_revoked` or
`superseded`, the sidecar reconnects with jittered exponential
backoff:

```
attempt 1:  1 s
attempt 2:  2 s
attempt 3:  4 s
attempt 4:  8 s
attempt 5: 16 s
attempt 6: 32 s
attempt 7+: 60 s (steady state)
```

Each delay is adjusted by ±25 % uniform jitter to prevent thundering
herds when the backend restarts. A successful handshake resets the
backoff counter.

**Hard stops — do not retry:**

- Received `auth_revoked` → exit process with code 0.
- Received `superseded` → exit process with code 0.
- Handshake `accepted: false` with a notice containing
  `"version_unsupported"` → exit process with code 2 (signals the
  container orchestrator not to restart-loop).

**In-flight requests at disconnect time are lost.** The sidecar
MUST NOT attempt to complete or replay them after reconnect. The
backend will surface an error to the consumer who can retry.

---

## 13. Healthcheck

The sidecar exposes a plain HTTP server on a loopback interface
bound to `SIDECAR_HEALTH_PORT` (default `8080`):

```
GET /healthz
```

Response when healthy:

```
200 OK
Content-Type: application/json

{
  "ok": true,
  "backend_connection": "connected",
  "engine": { "type": "ollama", "reachable": true },
  "uptime_seconds": 12345
}
```

Response when the backend connection is down:

```
503 Service Unavailable
Content-Type: application/json

{
  "ok": false,
  "backend_connection": "disconnected",
  "engine": { "type": "ollama", "reachable": true },
  "uptime_seconds": 12345
}
```

Semantics:

- `backend_connection` ∈ `{"connected", "reconnecting",
  "disconnected"}`. `reconnecting` is healthy-ish (return 200).
  `disconnected` (we have given up) returns 503.
- `engine.reachable` reflects the sidecar's last engine probe. It
  does NOT cause a non-200 response on its own — a sidecar with a
  temporarily unreachable engine can still be a useful process
  (it will return `engine_unavailable` errors on requests, which is
  the correct outcome).

This endpoint MUST NOT require authentication and MUST NOT be
exposed on a non-loopback interface by default. Docker
`healthcheck` hits it locally.

---

## 14. Environment Variables

Required in every sidecar build:

| Variable | Example | Purpose |
|---|---|---|
| `CHATSUNE_BACKEND_URL` | `wss://chat.example.com` | Base wss URL of the Chatsune backend. `/ws/sidecar` is appended by the sidecar. |
| `CHATSUNE_HOST_KEY` | `cshost_...` | Per-sidecar secret issued in the Chatsune UI. |

Per-engine (only the one used by this sidecar binary):

| Variable | Default | Applies to |
|---|---|---|
| `OLLAMA_URL` | `http://host.docker.internal:11434` | Ollama sidecar |
| `LMSTUDIO_URL` | `http://host.docker.internal:1234` | LM Studio sidecar |
| `VLLM_URL` | `http://host.docker.internal:8000` | vLLM sidecar |
| `LLAMACPP_URL` | `http://host.docker.internal:8080` | llama.cpp sidecar |

Optional:

| Variable | Default | Purpose |
|---|---|---|
| `SIDECAR_HEALTH_PORT` | `8080` | Port for the local healthcheck HTTP server. |
| `SIDECAR_LOG_LEVEL` | `info` | `debug`, `info`, `warn`, `error`. |
| `SIDECAR_MAX_CONCURRENT_REQUESTS` | engine-specific sensible default | Overrides what the sidecar advertises in handshake. |

The sidecar MUST refuse to start if `CHATSUNE_BACKEND_URL` or
`CHATSUNE_HOST_KEY` is missing. It MUST validate that
`CHATSUNE_HOST_KEY` starts with `cshost_` before even attempting a
connection — early misconfiguration detection.

---

## 15. Engine Translation

This section specifies how each supported engine's native API maps
to CSP. The first reference sidecar implements **Ollama only**; the
others are documented here so that the protocol's generality is
verifiable, and so that the second and third sidecar implementations
can ship without surprises.

### 15.1 Ollama

**API docs:** <https://github.com/ollama/ollama/blob/main/docs/api.md>

**Model listing:** `GET /api/tags` returns models with `name`, `size`,
`details.parameter_size` (string like `"8B"`, parse to int), and
`details.quantization_level`. For `context_length` the sidecar calls
`POST /api/show {"model": "<name>"}` and reads
`model_info["<arch>.context_length"]` (e.g.
`model_info["llama.context_length"]`).

**Chat completion:** `POST /api/chat` with
`{"model": "...", "messages": [...], "stream": true, "options": {...}}`.
Ollama's streamed response lines are `{"message": {"role":
"assistant", "content": "..."}}` plus an optional `done: true` line
with `prompt_eval_count` and `eval_count`.

**Reasoning:** Ollama emits `<think>...</think>` markers in `content`
for thinking-capable models. The sidecar MUST parse these out and
emit the inner content on the `reasoning` channel.

**Tool calls:** Recent Ollama versions produce OpenAI-style
`message.tool_calls`. Stream fragments correspondingly.

**Capabilities detection:** Ollama does not advertise capabilities
per model explicitly; the sidecar infers:

- `text` — always.
- `tool_calling` — present if the `/api/chat` response for the model
  declares tool support (runtime probe at `list_models` time —
  Ollama returns `"capabilities": ["tools"]` in `/api/show` since
  recent versions).
- `vision` — present if `/api/show` reports
  `model_info["<arch>.vision"]` truthy or a known VLM family.
- `reasoning` — present if the family is known thinker (`deepseek-r1`,
  `qwen3-thinking`, etc.); the sidecar maintains a local allowlist.

**Cancellation:** Close the HTTP stream.

### 15.2 LM Studio

**API docs:** <https://lmstudio.ai/docs/api>

OpenAI-compatible at `/v1/chat/completions` with streaming.
`GET /v1/models` for listing (sparse metadata — use a local lookup
table + GGUF inspection on the loaded model file when exposed via
LM Studio's `/api/v0` informational endpoints).

### 15.3 vLLM

**API docs:** <https://docs.vllm.ai/en/stable/serving/openai_compatible_server.html>

OpenAI-compatible at `/v1/chat/completions`, `/v1/models`. vLLM
supports tool calling natively on compatible models via
`--enable-auto-tool-choice`.

### 15.4 llama.cpp

**`server` docs:** <https://github.com/ggerganov/llama.cpp/blob/master/examples/server/README.md>

OpenAI-compatible at `/v1/chat/completions`. `GET /props` exposes
the loaded model's `n_ctx` (context length) and `default_generation_settings`.
For listing, `server` typically exposes one model at a time; the
sidecar represents it as a one-element list.

### 15.5 Metadata gap handling

Engines vary enormously in what they self-report. The sidecar MUST:

- **Drop any model for which `context_length` cannot be determined.**
  This mirrors the Chatsune `ollama_http` adapter's existing
  behaviour (INS-019 in the backend codebase) — a model whose max
  context window is unknown cannot be safely offered.
- **Fill missing fields with best-effort lookups** before giving up:
  - Local GGUF metadata inspection for llama.cpp / LM Studio
    (GGUF headers contain rich metadata).
  - A bundled lookup table keyed by base-model name (e.g.
    `llama3.2:8b` → 128k context, 8.03B params, Q4_K_M if not
    self-reported).
- **Never fabricate** values. If the sidecar cannot determine
  `capabilities`, advertise a conservative subset (`["text"]`) rather
  than guess.

---

## 16. Logging & Observability

- Log to stdout in **JSON Lines** format. Each line one object with
  at minimum: `ts` (ISO-8601), `level`, `event`, `message`.
- Log at `info` on: startup, handshake outcome, each `req`
  start/end with duration, disconnects, reconnect attempts.
- Log at `debug` on: every frame received and sent (with `id`,
  `type`, sizes).
- Log at `warn` on: missed pongs, engine reconnect attempts, parsing
  oddities.
- Log at `error` on: engine-unreachable, protocol violations, TLS
  failures.
- **Never log the Host-Key.** Log only the last 4 characters if
  identification is needed.
- **Never log user message content or tool arguments by default.**
  Those may contain PII. Redact at `info` and above. `debug` level
  MAY include them, but `debug` is opt-in via `SIDECAR_LOG_LEVEL`.

---

## 17. Container Conventions

Reference image: `ghcr.io/<org>/chatsune-sidecar-ollama:<version>`.

**Process model.** One process, foreground, logs to stdout. No
supervisor, no init system, no cron.

**Filesystem.** No persistent state expected. The image should run
read-only (`docker run --read-only`), with `tmpfs` for `/tmp` if
needed. A restart discards no meaningful state.

**User.** Run as non-root (`USER 10001:10001` or similar). No
capabilities required.

**Startup.**

1. Read env vars. Fail fast on missing `CHATSUNE_BACKEND_URL` /
   `CHATSUNE_HOST_KEY`.
2. Start the local healthcheck HTTP server on `SIDECAR_HEALTH_PORT`.
3. Probe the engine (e.g. `GET /api/version` for Ollama). Log the
   result. Do NOT fail startup if the engine is unreachable — the
   healthcheck will report it, and the backend will see
   `engine_unavailable` errors on requests.
4. Open the WebSocket to the backend, perform handshake.
5. Enter the frame loop.

**Shutdown.** On `SIGTERM` / `SIGINT`: send `stream_end {
"cancelled" }` for every in-flight request, close the WebSocket with
code `1001` (going away), then exit 0. Do not take longer than
5 seconds from signal to exit.

**Example `compose.yml` snippet (Ollama sidecar):**

```yaml
services:
  chatsune-sidecar:
    image: ghcr.io/<org>/chatsune-sidecar-ollama:1.0.0
    restart: unless-stopped
    environment:
      CHATSUNE_BACKEND_URL: wss://chat.example.com
      CHATSUNE_HOST_KEY: ${CHATSUNE_HOST_KEY}
      OLLAMA_URL: http://host.docker.internal:11434
    extra_hosts:
      - "host.docker.internal:host-gateway"
    healthcheck:
      test: ["CMD", "wget", "-q", "-O-", "http://127.0.0.1:8080/healthz"]
      interval: 30s
      timeout: 5s
      retries: 3
```

---

## 18. Deliverables for the First Reference Sidecar (Ollama)

The sidecar repository should ship, in order:

1. A minimal Python 3.12 sidecar that implements this spec for
   Ollama, using `websockets` for the WS transport and
   `httpx.AsyncClient` for engine calls. Asyncio throughout.
2. A `Dockerfile` producing the image described in §17.
3. A `README.md` with install, configure, run instructions, plus a
   link back to this spec.
4. A `.env.example` listing all env vars from §14.
5. A test suite with:
   - Unit tests for frame parsing / serialisation (Pydantic
     models covering every frame type in §5).
   - Unit tests for the engine translation layer using a recorded
     Ollama fixture (`pytest-vcr` or a handwritten mock).
   - An integration test that runs a fake Chatsune backend
     (one of the tests' `asyncio` WS servers) and drives the
     sidecar through a full `handshake` → `list_models` →
     `generate_chat` with cancel → disconnect → reconnect cycle.

Licence: **GPL-3.0**, matching Chatsune's open-source default.

---

## 19. Compatibility & Future Versions

- CSP/1 is frozen once the first sidecar ships. Additions that do
  not break existing sidecars (new capabilities, new optional
  fields, new `engine.type` values) bump the **minor** version.
- CSP/2 is reserved for breaking changes (frame renames, required
  field removals, transport change). CSP/2 sidecars MUST still
  handle CSP/1 handshakes where the backend has not yet upgraded,
  by negotiating down to CSP/1 — sidecars always speak the min of
  what they support and what the backend supports.
- The sidecar spec document is versioned in lockstep with the
  protocol. New CSP minor/major versions get a new spec file.

---

## 20. Open Items (for implementers to flag back)

Not blockers, but feedback welcome during the first implementation:

- **Streaming cancel latency.** Measure how long Ollama takes to
  actually stop producing tokens after the HTTP stream is closed,
  with a 70B model under load. If > 1 s typical, consider
  `POST /api/generate` with a future cancel endpoint.
- **Engine version probing cost.** If `GET /api/show` for every
  model blows up `list_models` latency noticeably, cache per-model
  metadata within the sidecar with a 5-minute TTL.
- **GGUF inspection footprint.** For the LM Studio / llama.cpp
  sidecars, native GGUF parsing would be nice; worth checking if a
  small Python library exists before writing one.
- **Reconnect behaviour on backend TLS rotation.** If the backend
  rotates its cert mid-flight, the sidecar should reconnect
  cleanly. Worth a deliberate test.
