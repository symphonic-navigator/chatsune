# MCP Polish — Tool-Call Pills with Result + Streamable HTTP — Design

**Date:** 2026-05-10
**Status:** Draft
**Branch:** `feat/mcp-polish`

---

## 1. Context & Problem

Two distinct issues, bundled into one polish package because they share the
same surface area (the MCP integration):

### 1.1 Tool-call pills hide the response

In the chat view, every backend-executed tool call produces a small pill on
the assistant message (`frontend/src/features/chat/ToolCallPills.tsx`). The
pill is expandable and currently shows the **arguments** of the call, but
not the **result**. The result content lives on a separate `role: "tool"`
message keyed by `tool_call_id`, but the pill never reads it.

Tester feedback (four people on the same day): "it's hard to see actual
progress without output", followed by "we need to see what the tool call
returned". The pill is the natural place — it is already where users go
when they want detail on a specific call.

### 1.2 HTTP transport not compliant with MCP Streamable HTTP

The backend MCP executor (`backend/modules/tools/_mcp_executor.py`) issues
JSON-RPC POSTs against a gateway's `/mcp` endpoint with only:

- `Content-Type: application/json`
- `Authorization: Bearer …` (when an API key is set)

Two consequences observed during ad-hoc testing against a self-hosted
server:

1. The server (a strict implementation) rejects requests that omit
   `Accept: application/json` outright.
2. FastMCP — the most common Python MCP framework — defaults to
   `Streamable HTTP` transport. When a client sends `Accept: …,
   text/event-stream`, FastMCP may answer with `Content-Type:
   text/event-stream` and a single SSE `data: {jsonrpc-response}` event
   followed by stream close. Our executor calls `resp.json()` on what is
   not a JSON body and crashes.

Both issues are minor in scope but make Chatsune incompatible with two
common MCP server implementations users actually run.

## 2. Goals & Non-Goals

**Goals**
- Pill expand-popover shows the tool's response text alongside its
  arguments, so testers can inspect what came back.
- Backend executor advertises `Accept: application/json,
  text/event-stream` on every MCP request and correctly handles a
  `text/event-stream` response by parsing the SSE stream until the
  matching JSON-RPC reply is received.
- No regression for existing JSON-only servers.

**Non-goals**
- `Mcp-Session-Id` stateful session management. Our tool calls are
  one-shot; we do not need session continuity across requests.
- Server-initiated message channel via `GET /mcp`. We do not need
  bidirectional messaging for tool calls.
- Surfacing `notifications/progress` as live UI events. This would solve
  "see progress" more deeply than just showing the final result, but is a
  separate feature with its own pipeline (decision: out-of-scope, can be
  added later if pills-with-results turn out to be insufficient).
- Backfilling `result_content` on historical messages already persisted
  before this change. Forward-only — see §5.4.
- Non-text content parts in the response display (image, resource, etc.).
  We extract only `content[].text` and concatenate, matching the existing
  executor behaviour at `_mcp_executor.py:78`.
- Truncation of long results — the popover gets a max-height with scroll
  rather than chopping the response.

## 3. Architecture

The change touches three layers; each layer's contract is small and
independent of the others.

```
┌──────────────────────────────────────────────────────────────────┐
│  Frontend  ToolCallPills.tsx                                     │
│   • Reads ToolCallRef.result_content (new)                       │
│   • Renders Request + Response sections in expand popover        │
└──────────────────────────────────────────────────────────────────┘
                               ▲
                               │ ToolCallRefDto / TimelineEntryToolCall
                               │ (+ result_content: str | None)
                               │
┌──────────────────────────────────────────────────────────────────┐
│  Shared DTOs  shared/dtos/chat.py                                │
│   • ToolCallRefDto.result_content: str | None = None             │
│   • TimelineEntryToolCall.result_content: str | None = None      │
└──────────────────────────────────────────────────────────────────┘
                               ▲
                               │ written by orchestrator
                               │
┌──────────────────────────────────────────────────────────────────┐
│  Backend  Chat orchestrator + MCP executor                       │
│   • Orchestrator: stash extracted result text per tool_call_id,  │
│     write into ToolCallRef before persisting assistant message.  │
│   • Executor: Accept header on every request. Branch on response │
│     Content-Type (json | sse) to obtain the JSON-RPC reply.      │
└──────────────────────────────────────────────────────────────────┘
```

## 4. Detailed Design — Punkt 1: Pills with Result

### 4.1 DTO additions (`shared/dtos/chat.py`)

```python
class ToolCallRefDto(BaseModel):
    tool_call_id: str
    tool_name: str
    arguments: dict
    success: bool
    moderated_count: int = 0
    result_content: str | None = None   # NEW
```

```python
class TimelineEntryToolCall(BaseModel):
    kind: Literal["tool_call"] = "tool_call"
    seq: int
    tool_call_id: str
    tool_name: str
    arguments: dict
    success: bool
    moderated_count: int = 0
    result_content: str | None = None   # NEW
```

Default `None` makes the change strictly additive. Existing MongoDB
documents deserialise without modification — this satisfies the "no more
wipes" rule (CLAUDE.md §"Data Model Migrations").

The same field is mirrored in the TS interface
`frontend/src/core/api/chat.ts`:

```typescript
interface ToolCallRef {
  tool_call_id: string
  tool_name: string
  arguments: Record<string, unknown>
  success: boolean
  moderated_count?: number
  result_content?: string | null   // NEW
}

interface TimelineEntryToolCall {
  kind: 'tool_call'
  seq: number
  tool_call_id: string
  tool_name: string
  arguments: Record<string, unknown>
  success: boolean
  moderated_count?: number
  result_content?: string | null   // NEW
}
```

### 4.2 Backend population

The chat orchestrator (`backend/modules/chat/_orchestrator.py`, around
the existing `tool_call_id` flow at line ~315–360) already has the result
in hand: `_mcp_executor.call_tool` returns
`{"stdout": <text>, "error": <text|None>}` as a JSON string. The text
extraction logic lives at `_mcp_executor.py:74–79`.

Capture both halves into a per-call result string:

- On success (`error is None`): `result_content = stdout`
- On error: `result_content = error`
- On the `success: false` branch (failure to dispatch / executor crash):
  same — whatever error string the executor produced.

When the assistant message is finalised and persisted, write
`result_content` onto each `ToolCallRef` and the corresponding
`TimelineEntryToolCall` for that `tool_call_id`. The existing tool-role
message that carries the same content stays untouched — we are not
de-duplicating storage here, the duplication is intentional and bounded
by message lifetime.

For client-executed tools (browser-side handlers, see
`frontend/src/features/code-execution/clientToolHandler.ts`), the same
field is populated when the result is sent back to the backend before
the assistant message is sealed.

### 4.3 Frontend rendering

Update `frontend/src/features/chat/ToolCallPills.tsx`:

- Keep the closed pill exactly as it is.
- In the expand popover, restructure into two labelled sections:

```
┌──────────────────────────────────────────┐
│ tool_name                                │
│                                          │
│ Request                                  │
│ key: value                               │
│ key2: value2                             │
│                                          │
│ Response                                 │
│ … extracted text content …               │
└──────────────────────────────────────────┘
```

- "Response" section is omitted entirely when `result_content` is
  `null` or `undefined` (forward-only behaviour for old messages, and
  also the live-streaming state where the tool has been *called* but
  has not yet returned).
- Long results: popover gets `max-height: 320px` with `overflow-y: auto`.
  No string truncation. Monospace font, same styling as the Request
  section so the visual rhythm is preserved.
- Section labels use the same colour as the existing pill foreground
  (`rgba(${colour},0.9)`) at `text-[10px]` to match the existing tool
  name header.

A short Vitest covers: (a) renders Response when `result_content` is
present, (b) hides Response section when `null`, (c) `success: false`
still renders the Response section (error text is content too).

## 5. Detailed Design — Punkt 2: Streamable HTTP

### 5.1 Headers

Both `call_tool` and `discover_tools` in
`backend/modules/tools/_mcp_executor.py` get the same header set:

```python
headers = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}
if api_key:
    headers["Authorization"] = f"Bearer {api_key}"
```

The Accept header goes out **always**, regardless of which response path
the server ends up choosing — the client signals "I can read either
shape", the server picks.

### 5.2 Response dispatch

Replace the current `client.post(...)` + `resp.json()` shape with a
streaming-capable call that inspects `Content-Type` after headers
arrive:

```python
async with httpx.AsyncClient(timeout=_MCP_HTTP_TIMEOUT_S) as client:
    async with client.stream("POST", url, json=payload, headers=headers) as resp:
        ctype = resp.headers.get("content-type", "").split(";", 1)[0].strip().lower()

        if ctype == "application/json":
            body_bytes = await resp.aread()
            body = json.loads(body_bytes)

        elif ctype == "text/event-stream":
            body = await _read_sse_response(resp, expected_id=payload["id"])

        else:
            return _error(f"unexpected content-type: {ctype}")
```

Resolution proceeds with the existing `body` handling (JSON-RPC error
field check, `result.content[].text` extraction).

### 5.3 SSE reader (`_read_sse_response`)

A small helper, private to `_mcp_executor.py`, parses an SSE stream
until a JSON-RPC payload with the expected `id` arrives:

```python
async def _read_sse_response(resp: httpx.Response, expected_id: int) -> dict:
    """Read an SSE stream, return the first JSON-RPC payload matching expected_id.

    Notifications (no `id`) and unrelated messages are silently skipped.
    Raises on stream end without a matching response.
    """
    async for line in resp.aiter_lines():
        if not line.startswith("data:"):
            continue   # ignore event:, id:, retry:, comments, blank lines
        data = line[5:].lstrip()
        if not data:
            continue
        try:
            obj = json.loads(data)
        except json.JSONDecodeError:
            _log.warning("MCP SSE: malformed data line: %r", data[:120])
            continue
        if obj.get("id") == expected_id:
            return obj
        # else: notification or stray response — skip
    raise RuntimeError("SSE stream closed without matching response")
```

Notes:
- `httpx`'s `aiter_lines()` already handles `\n` / `\r\n` line endings
  and chunk reassembly.
- We do not implement event coalescing (multi-line `data:` accumulation
  across blank-line-separated events). MCP responses are a single JSON
  object per `data:` line in practice; if a server splits across multi-
  line `data:` events, that is a future-extension problem.
- We do not honour `event:` types — for our use case the only event we
  care about is the unnamed default with a JSON-RPC body.

### 5.4 No backfill

This is forward-only. Old persisted messages keep `result_content =
None`; the pill simply omits the Response section for them. The tester
cohort is small enough that nobody loses meaningful history. If a tester
needs to inspect an old result, the corresponding `role: "tool"` message
still carries the content (visible in any DB tooling, not in the UI).

## 6. Error handling

### 6.1 Pills

- `result_content == null` → no Response section rendered.
- `success == false` with `result_content` set → Response section shows
  the error text. The pill foreground remains in the existing "error"
  colour (`243,139,168`).
- `success == false` with `result_content == null` (legacy data or
  early failure before result was captured) → Response section omitted;
  the existing red pill colour already signals "this failed".

### 6.2 Executor

- HTTP timeout / connection failure: existing path — return JSON string
  with `error` field. Unchanged.
- SSE stream closes before a matching `id` arrives: log warning, return
  the same `MCP gateway unreachable` style error JSON string.
- SSE `data:` line is malformed: log warning, continue to next line —
  do not abort the whole stream over one bad line.
- Unexpected `Content-Type`: return error JSON string identifying the
  content-type so triage is fast.

## 7. Testing

### 7.1 Backend pytest

Under `backend/modules/tools/__tests__/` (or wherever the existing MCP
tests live — discovered during implementation):

- `test_mcp_executor_sends_accept_header` — assert both
  `application/json` and `text/event-stream` are present in the Accept
  header for `call_tool` and `discover_tools`.
- `test_mcp_executor_handles_json_response` — mock httpx to return
  `Content-Type: application/json` + body; assert the extracted text.
- `test_mcp_executor_handles_sse_response` — mock httpx to stream
  `data: {"jsonrpc":"2.0","id":N,"result":{...}}\n\n`; assert the
  extracted text.
- `test_mcp_executor_skips_sse_notifications` — stream a
  `notifications/progress` event followed by the real reply; assert
  the real reply wins.
- `test_mcp_executor_handles_sse_close_without_response` — stream that
  closes early; assert error JSON string is returned, not a raise.

### 7.2 Frontend Vitest

Under `frontend/src/features/chat/__tests__/`:

- `test_ToolCallPills_renders_request_and_response` — both sections
  visible when `result_content` is set.
- `test_ToolCallPills_hides_response_when_null` — only Request
  section.
- `test_ToolCallPills_renders_response_for_failed_call` — `success:
  false` with error text in `result_content`.

### 7.3 Build verification

- `pnpm run build` must pass after the TS interface change (per
  CLAUDE.md, not just `tsc --noEmit`).
- Backend: `uv run python -m py_compile <changed files>` per CLAUDE.md.
- DB-using backend tests are excluded on host (per memory
  `db_tests_on_host`).

## 8. Manual verification

These steps are run on a real machine with the dev stack up.

1. **Pills with response — happy path**
   - Start backend + frontend (`docker compose up` or local dev).
   - In a chat with an MCP gateway configured, ask the assistant to
     run a tool that returns a non-trivial text result (e.g. an
     `httpbin`-style echo or a `quotes_about` tool).
   - Click the resulting pill. Confirm: Request section shows arguments
     unchanged; Response section shows the tool's text output.
   - Long output (≥ 1 KB): popover scrolls instead of overflowing.

2. **Pills with response — error path**
   - Trigger a failing tool call (wrong argument shape, or
     deliberately broken tool).
   - Confirm: pill is red. Click. Response section shows the error
     text rather than being absent.

3. **Pills with response — legacy data**
   - Open an existing chat that has tool calls from before this
     change (`result_content` will be `None` in MongoDB).
   - Click the pill. Confirm: Request section unchanged; Response
     section is absent (no empty box).

4. **Streamable HTTP — JSON-only server**
   - Configure a gateway pointing at a server that always returns
     `Content-Type: application/json` (current Chatsune-internal
     server, or any classical JSON-RPC MCP server).
   - Run a tool call. Confirm: works exactly as before, pill shows
     the result.

5. **Streamable HTTP — FastMCP server**
   - Configure a gateway pointing at a FastMCP-default server (the
     server Chris has running for this round of testing).
   - Run a tool call. Confirm: response arrives, pill shows the
     result. No "Expecting value" or JSON-decode errors in backend
     logs.
   - Backend log shows the call hit the SSE branch (look for the
     `text/event-stream` content-type log line — added during
     implementation).

6. **Streamable HTTP — Accept header always present**
   - With backend running, watch logs (or use `tcpdump` /
     `mitmproxy`) and confirm every outgoing MCP request carries
     `Accept: application/json, text/event-stream`, including
     `tools/list` discovery on session start.

## 9. Rollout

- Single feature branch `feat/mcp-polish`.
- One subagent-driven implementation pass (per Chatsune defaults).
- Merge to master after manual verification (per Chatsune defaults).
- No flag, no staged rollout — the change is local, reversible by
  revert, and improves baseline behaviour.

## 10. Open questions

None at this stage. All four clarification points (response shape,
result delivery path, transport scope, legacy backfill) are resolved
above.
