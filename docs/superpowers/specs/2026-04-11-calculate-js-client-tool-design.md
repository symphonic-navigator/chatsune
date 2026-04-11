# `calculate_js` — Client-Side Code Execution (Design)

**Date:** 2026-04-11
**Status:** Design approved, ready for implementation
**Scope:** New tool `calculate_js` plus the first productive use of the
client-side tool forwarding infrastructure that has so far existed only as a
placeholder (`ToolGroup.side` field).

---

## Context

Chatsune's backend already anticipates client-side tool execution: the
`ToolGroup` dataclass in `backend/modules/tools/_registry.py:25` has a
`side: Literal["server", "client"]` field, and INS-010 explicitly notes that
client-side tools were planned with Pyodide in mind. No tool has ever used
the `"client"` side — it is a pure placeholder today.

The `PYODIDE.md` document captures a prior brainstorming session about a
full Python code interpreter in the browser. That direction stalled on
scope: a full Pyodide integration is a sub-project, not a feature, and
touches the artefact system, download flow, sandbox limits, and ~10 MB of
WASM payload.

This spec takes a different cut. Instead of building the ambitious version
first, it builds the **smallest possible client-side tool** that exercises
the complete forwarding architecture — a plain JavaScript evaluator in a
Web Worker sandbox, used as a programmable calculator for arithmetic,
string operations, and JSON handling. Concretely:

- The r-counting meme ("how many `r` in erdbeere") — weaker models get this
  wrong because character counting is token-count-hostile.
- Exact arithmetic (e.g. `BigInt` support for numbers beyond `2^53`).
- String transformations and JSON parsing that would otherwise be done by
  the LLM by pattern-matching.

The strategic value is not the calculator itself — it is that the entire
architectural scaffolding for client-side tool forwarding gets built and
productively tested with a tiny sandbox payload. When Pyodide (or any other
in-browser interpreter) is revisited, it is just another `ToolGroup` with
`side="client"`; no further architectural work.

---

## Goals

1. Add a new tool `calculate_js` that executes short JavaScript snippets in
   a locked-down Web Worker and returns captured `console.log` output to
   the LLM.
2. Build the full client-side tool forwarding infrastructure: the server's
   inference loop transparently routes `side="client"` tool calls to the
   originating browser, waits for the result, and feeds it back into the
   tool loop exactly like a server-side tool result.
3. Introduce *targeted* event delivery (server → one specific WebSocket
   connection) so that multi-tab sessions do not trigger duplicate tool
   executions.
4. Keep every failure path terminal: no Python exception from
   `execute_tool` for the calculate path, no leaked `asyncio.Future`, no
   orphaned Worker, no indefinite wait.
5. Make the tool toggleable per session via the existing tool-group toggle
   UI, consistent with `web_search` and `artefacts`.

## Non-Goals

- **No Pyodide, no WASM, no Python in the browser.** `calculate_js` is pure
  JavaScript.
- **No namespace persistence between calls.** Every execution is isolated;
  there is no REPL-like state.
- **No DOM, no network, no timers, no imports** inside the sandbox.
- **No tools other than `calculate_js`.** The `code_execution` tool group
  contains exactly one tool.
- **No changes to any existing server-side tool** (`web_search`,
  `knowledge_search`, `artefacts`, etc.). The dispatch path for
  `side="server"` remains identical.
- **No Python-side test fuzzing of the sandbox** — Web Worker isolation is
  a browser primitive; we do not re-test the browser.
- **No new persistence.** Tool-call messages remain ephemeral per INS-010;
  nothing is written to MongoDB.

---

## Design

### 1. Shared contracts

#### 1.1 New topic constant

In `shared/topics.py`:

```python
CHAT_CLIENT_TOOL_DISPATCH = "chat.client_tool.dispatch"
```

#### 1.2 New event — `ChatClientToolDispatchEvent`

In `shared/events/chat.py`:

```python
class ChatClientToolDispatchEvent(BaseModel):
    type: str = "chat.client_tool.dispatch"
    session_id: str
    tool_call_id: str           # LLM-SDK-provided correlation id
    tool_name: str              # e.g. "calculate_js"
    arguments: dict             # raw tool arguments, e.g. {"code": "..."}
    timeout_ms: int             # budget the client has before its Worker
                                # is terminated (always smaller than the
                                # server-side wait budget)
    target_connection_id: str   # originating WebSocket connection
```

The `timeout_ms` is carried in the event so the client does not hardcode
the value — the authoritative number lives in
`backend/modules/tools/__init__.py`.

The `target_connection_id` is the mechanism used by the event bus fanout
to deliver the event to exactly one browser tab (see §2.5).

#### 1.3 New DTOs for the inbound client→server message

In `shared/dtos/tools.py`:

```python
class ClientToolResultPayload(BaseModel):
    stdout: str
    error: str | None

class ClientToolResultDto(BaseModel):
    tool_call_id: str
    result: ClientToolResultPayload
```

These DTOs validate the `chat.client_tool.result` WebSocket message that
the browser sends back with the sandbox's output.

### 2. Backend

#### 2.1 Extended `execute_tool` dispatch

In `backend/modules/tools/__init__.py`, `execute_tool` grows two keyword
arguments and gains a client-side branch:

```python
async def execute_tool(
    user_id: str,
    tool_name: str,
    arguments_json: str,
    *,
    tool_call_id: str,
    session_id: str,
    originating_connection_id: str,
) -> str:
    arguments = json.loads(arguments_json)

    for group in get_groups().values():
        if tool_name not in group.tool_names:
            continue

        if group.side == "client":
            return await _client_dispatcher.dispatch(
                user_id=user_id,
                session_id=session_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                arguments=arguments,
                timeout_ms=_CLIENT_TOOL_SERVER_TIMEOUT_MS,
                target_connection_id=originating_connection_id,
            )

        if group.executor is not None:
            return await group.executor.execute(user_id, tool_name, arguments)

    raise ToolNotFoundError(f"No executor registered for tool '{tool_name}'")
```

The explicit `side == "client"` check happens **before** the
`executor is not None` check, which is important because the new
`code_execution` group sets `executor=None` (there is no server-side
executor for client-side tools).

Timeout constants:

```python
_CLIENT_TOOL_SERVER_TIMEOUT_MS = 10_000   # total server-side wait budget
_CLIENT_TOOL_CLIENT_TIMEOUT_MS = 5_000    # hard budget communicated to the
                                          # browser Worker; the 5 000 ms
                                          # difference is the network and
                                          # scheduler buffer.
```

The value sent in `ChatClientToolDispatchEvent.timeout_ms` is
`_CLIENT_TOOL_CLIENT_TIMEOUT_MS`.

#### 2.2 `ClientToolDispatcher`

New module-internal file `backend/modules/tools/_client_dispatcher.py`.
Exported via `backend/modules/tools/__init__.py` as
`get_client_dispatcher()`.

```python
class ClientToolDispatcher:
    def __init__(self) -> None:
        # tool_call_id -> (user_id, asyncio.Future[str])
        self._pending: dict[str, tuple[str, asyncio.Future[str]]] = {}

    async def dispatch(
        self,
        *,
        user_id: str,
        session_id: str,
        tool_call_id: str,
        tool_name: str,
        arguments: dict,
        timeout_ms: int,
        target_connection_id: str,
    ) -> str:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        self._pending[tool_call_id] = (user_id, future)

        try:
            await get_event_bus().publish(
                Topics.CHAT_CLIENT_TOOL_DISPATCH,
                ChatClientToolDispatchEvent(
                    session_id=session_id,
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    arguments=arguments,
                    timeout_ms=timeout_ms,
                    target_connection_id=target_connection_id,
                ),
                scope=f"user:{user_id}",
                target_user_ids=[user_id],
                target_connection_id=target_connection_id,
                correlation_id=tool_call_id,
            )
            return await asyncio.wait_for(future, timeout=timeout_ms / 1000)
        except asyncio.TimeoutError:
            return json.dumps({
                "stdout": "",
                "error": f"Tool execution timed out after {timeout_ms}ms",
            })
        finally:
            self._pending.pop(tool_call_id, None)

    def resolve(
        self,
        *,
        tool_call_id: str,
        received_from_user_id: str,
        result_json: str,
    ) -> None:
        pending = self._pending.get(tool_call_id)
        if pending is None:
            _log.warning(
                "client_tool_result for unknown tool_call_id=%s from user=%s",
                tool_call_id, received_from_user_id,
            )
            return

        expected_user_id, future = pending
        if expected_user_id != received_from_user_id:
            _log.warning(
                "client_tool_result user mismatch: tool_call_id=%s "
                "expected=%s received=%s (dropped)",
                tool_call_id, expected_user_id, received_from_user_id,
            )
            return

        if not future.done():
            future.set_result(result_json)

    def cancel_for_user(self, user_id: str) -> None:
        for call_id, (uid, future) in list(self._pending.items()):
            if uid == user_id and not future.done():
                future.set_result(json.dumps({
                    "stdout": "",
                    "error": "Client disconnected before tool completed",
                }))
```

Three deliberate choices:

- **Synthetic error results instead of exceptions.** Every failure path
  (timeout, disconnect, mismatch) ends in a `{stdout, error}` JSON string.
  The inference loop keeps flowing; the LLM sees an error it can reason
  about.
- **User-ID check in `resolve`.** Defence in depth: cheap (one comparison)
  and protects against future leaks of `tool_call_id`s. See the threat
  model note in §5.
- **Strict first-writer-wins via `if not future.done()`.** Duplicate
  responses (which should never occur with targeted fanout, but might from
  a buggy client) are silently ignored.

#### 2.3 Inference runner wiring

In `backend/modules/chat/_inference.py`, the `execute_tool` call site needs
three extra arguments, all of which are already in scope at the call
point: `tool_call_id` (from the LLM SDK's tool-call object),
`session_id` (from the running chat session context), and
`originating_connection_id` (see §2.4).

No semantic change to the loop's behaviour — the existing server-side tool
path takes the same branch it took before.

#### 2.4 Connection-ID threading

The new `originating_connection_id` parameter must be threaded from the
WebSocket message handler down into `execute_tool`. The path is:

1. `backend/ws/router.py` — the incoming `chat.send_message` (or similar)
   handler already knows which `connection_id` the message arrived from
   (the WebSocket manager passes the connection context to handlers).
2. `backend/modules/chat/` — the chat module's public API gains an
   `originating_connection_id` parameter on the entrypoint that triggers
   inference.
3. `_orchestrator.py` / `_inference.py` — carried as a field on the
   in-memory inference context.
4. `execute_tool` receives it as a keyword argument.

If the WebSocket manager does not currently assign a stable connection id
to each accepted connection, that is added as part of this spec. The
connection id is a UUID generated at accept time and attached to the
connection object in `backend/ws/manager.py`.

The connection id is also communicated to the frontend as part of an
existing handshake/hello event, so the client knows its own identity
(used in §3.3 for sanity but not for filtering — filtering is done
server-side by the fanout).

#### 2.5 Targeted event bus fanout

`backend/ws/event_bus.py::publish()` gains a new optional parameter
`target_connection_id: str | None = None`. When provided, the fanout
delivers the event only to the connection with that exact id (and only
if it belongs to a user in `target_user_ids`). When `None`, the existing
behaviour is preserved: fan out to every connection of every user in
`target_user_ids`.

This is the mechanism by which `ChatClientToolDispatchEvent` reaches
exactly the tab that initiated the inference, with zero duplicate
executions across multi-tab sessions. The capability is general-purpose —
any future "this answer belongs to one tab" event (permission prompts,
file-picker dialogues, etc.) can use it.

**INS-011 reminder:** the new topic `CHAT_CLIENT_TOOL_DISPATCH` must be
added to `_FANOUT` in `backend/ws/event_bus.py`, otherwise it will be
persisted to Redis Streams but never delivered. This is an explicit
implementation step, not an afterthought.

#### 2.6 Inbound WebSocket handler

In `backend/ws/router.py`, a new handler for message type
`chat.client_tool.result`:

```python
async def handle_client_tool_result(
    user_id: str,
    connection_id: str,
    raw_payload: dict,
) -> None:
    try:
        dto = ClientToolResultDto.model_validate(raw_payload)
    except ValidationError as e:
        _log.warning(
            "malformed client_tool_result from user=%s: %s",
            user_id, e,
        )
        return

    get_client_dispatcher().resolve(
        tool_call_id=dto.tool_call_id,
        received_from_user_id=user_id,
        result_json=dto.result.model_dump_json(),
    )
```

The `connection_id` is not used for routing (the tool_call_id already
determines which future resolves) but is logged for observability.

#### 2.7 Disconnect hook

In `backend/ws/manager.py`, the connection-close path is extended to call
`get_client_dispatcher().cancel_for_user(user_id)` **only if** that user
has no remaining connections. This is one extra line. If the user has
other active connections, pending tool calls are left in place — the
user is still "there", just on a different tab.

Edge case: if the originating tab (to which the event was dispatched)
closes but another tab stays open, the tool call will still time out via
the server-side 10-second wait. That is acceptable — the user sees a
timeout error, not a hang.

#### 2.8 New tool group registration

In `backend/modules/tools/_registry.py::_build_groups()`:

```python
"code_execution": ToolGroup(
    id="code_execution",
    display_name="Code Execution",
    description=(
        "Run small JavaScript snippets for calculations, string "
        "operations, and JSON handling — executed in a sandboxed Web "
        "Worker in your browser. No network, no DOM, no state between "
        "calls."
    ),
    side="client",
    toggleable=True,
    tool_names=["calculate_js"],
    definitions=[
        ToolDefinition(
            name="calculate_js",
            description=(
                "Execute a short JavaScript snippet for calculations, "
                "string operations, or JSON handling. The snippet runs "
                "in an isolated sandbox with no network or state. Use "
                "console.log(...) to emit results — anything not logged "
                "is invisible to you. Typical uses: arithmetic that "
                "needs exact results, counting characters or substrings, "
                "parsing or reformatting JSON, date arithmetic. Do NOT "
                "use for anything that requires waiting, network access, "
                "or multiple steps across calls."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": (
                            "A self-contained JavaScript snippet. Must "
                            "emit its result via console.log. Maximum "
                            "runtime is a few seconds; maximum output "
                            "is a few kilobytes."
                        ),
                    },
                },
                "required": ["code"],
            },
        ),
    ],
    executor=None,  # no server-side executor — routed by side=="client"
),
```

The description is deliberately dual-natured: positive examples plus a
"Do NOT use for" negative clause. Empirically, weaker models (GLM,
DeepSeek) respond better to bounded guidance than to open-ended invitation.
The pattern is borrowed from the `create_artefact` description in the
existing code.

### 3. Frontend

#### 3.1 Module layout

New feature module under `frontend/src/features/code-execution/`:

```
frontend/src/features/code-execution/
  clientToolHandler.ts      ← subscribes to dispatch events, routes to host
  sandboxHost.ts            ← Worker lifecycle, timeout, result Promise
  sandbox.worker.ts         ← bootstrap script running inside the Worker
```

#### 3.2 `sandbox.worker.ts` — the bootstrap

Runs inside the Worker context. No imports (so `importScripts` is
sandboxed before anything else touches the global scope).

Responsibilities:

1. **Null out dangerous globals** before any user code runs:
   `fetch`, `XMLHttpRequest`, `WebSocket`, `importScripts`, `setTimeout`,
   `setInterval`, `clearTimeout`, `clearInterval`, `requestAnimationFrame`,
   `cancelAnimationFrame`, `Worker`, `SharedWorker`, `EventSource`,
   `BroadcastChannel`, `indexedDB`, `caches`. Each assignment is wrapped
   in `try { self[name] = undefined } catch {}` so that
   defineProperty-protected globals (should any exist) do not crash the
   bootstrap.
2. **Register a `message` listener** that accepts one request per Worker
   instance of shape `{code: string, maxOutputBytes: number}` and replies
   with `{stdout: string, error: string | null}`.
3. **Rebind `console.log`/`error`/`warn`/`info`** to an in-closure
   line-capturing function *before* running the user code. Output is
   collected in a `string[]`, with per-line byte counting via
   `TextEncoder().encode(...)`. Once the running byte total would exceed
   `maxOutputBytes`, the last line is truncated at the remaining budget
   and further `console.log` calls become no-ops. The response's `stdout`
   field ends with `"... (output truncated)"` when truncation happened.
4. **Execute the code via indirect eval** (`(0, eval)(code)`) so the user
   code runs in the Worker's global scope, not in the scope of the
   message handler — no accidental capture of handler-local variables.
5. **Wrap the eval in `try/catch`**. On exception, the response's `error`
   field is set to `"${name}: ${message}"`; any `console.log` lines
   captured before the exception are still returned in `stdout`.

Deliberately not included: no stack trace in `error` (context ballast for
the LLM and leaks paths), no `finally` cleanup (Worker is terminated after
the reply), no persistent state.

#### 3.3 `sandboxHost.ts` — Worker lifecycle

Creates a **new Worker per call** — this is the strongest possible form of
statelessness. No pooling, no reuse.

```typescript
export interface SandboxResult {
  stdout: string
  error: string | null
}

export async function runSandbox(
  code: string,
  timeoutMs: number,
  maxOutputBytes: number,
): Promise<SandboxResult> {
  const worker = new Worker(
    new URL('./sandbox.worker.ts', import.meta.url),
    { type: 'module' },
  )

  const result = await new Promise<SandboxResult>((resolve) => {
    const timeoutHandle = setTimeout(() => {
      worker.terminate()
      resolve({
        stdout: '',
        error: `Client-side timeout after ${timeoutMs}ms`,
      })
    }, timeoutMs)

    worker.addEventListener('message', (event: MessageEvent<SandboxResult>) => {
      clearTimeout(timeoutHandle)
      resolve(event.data)
    })

    worker.addEventListener('error', (event: ErrorEvent) => {
      clearTimeout(timeoutHandle)
      resolve({
        stdout: '',
        error: `Sandbox crash: ${event.message || 'unknown error'}`,
      })
    })

    worker.postMessage({ code, maxOutputBytes })
  })

  worker.terminate()  // unconditional — covers the happy path
  return result
}
```

The timeout handler is responsible for resolving the Promise in the
timeout case, so the `await` always returns even when the Worker is
killed before it replies. This was explicitly discussed during
brainstorming because it is the kind of bug that is easy to introduce on
the first pass.

#### 3.4 `clientToolHandler.ts` — wiring to the WS store

Subscribes to `chat.client_tool.dispatch` events, validates the tool
name, extracts `arguments.code`, calls `runSandbox`, and sends a
`chat.client_tool.result` message back over the WebSocket store.

```typescript
const MAX_OUTPUT_BYTES = 4096

export function registerClientToolHandler(): () => void {
  return wsStore.onEvent('chat.client_tool.dispatch', async (event) => {
    if (event.tool_name !== 'calculate_js') {
      wsStore.sendMessage({
        type: 'chat.client_tool.result',
        tool_call_id: event.tool_call_id,
        result: {
          stdout: '',
          error: `Unknown client tool: ${event.tool_name}`,
        },
      })
      return
    }

    const code = typeof event.arguments?.code === 'string'
      ? event.arguments.code
      : ''
    if (!code) {
      wsStore.sendMessage({
        type: 'chat.client_tool.result',
        tool_call_id: event.tool_call_id,
        result: { stdout: '', error: 'No code provided' },
      })
      return
    }

    const result = await runSandbox(code, event.timeout_ms, MAX_OUTPUT_BYTES)
    wsStore.sendMessage({
      type: 'chat.client_tool.result',
      tool_call_id: event.tool_call_id,
      result,
    })
  })
}
```

Exact names (`wsStore.onEvent`, `wsStore.sendMessage`) depend on the
existing store interface and will be adjusted during implementation to
match the actual API.

`registerClientToolHandler()` is called once at app startup, alongside
other event subscriptions in `App.tsx` or equivalent.

**Stale-tab fallback:** if an old tab runs an older frontend version that
does not know the new event type, the dispatch event is silently dropped
and the server-side 10-second wait returns a timeout error. The chat
session continues. This is acceptable degradation.

### 4. Timeouts & failure matrix

All failure paths converge on a `{stdout, error}` JSON result fed back
into the tool loop. No exception escapes `execute_tool` for the
client-side path.

| Case | Where it is handled | Result delivered to the LLM |
|---|---|---|
| JS runs cleanly | Worker `postMessage` | `{"stdout": "...", "error": null}` |
| JS throws an exception | Worker `try/catch` | `{"stdout": "<partial>", "error": "TypeError: ..."}` |
| JS hangs >5 s | Client-side `setTimeout` in `sandboxHost` | `{"stdout": "", "error": "Client-side timeout after 5000ms"}` |
| Worker bootstrap crash | Worker `error` event in `sandboxHost` | `{"stdout": "", "error": "Sandbox crash: ..."}` |
| Output >4 KB | `captureLine` in worker bootstrap | `{"stdout": "<truncated>... (output truncated)", "error": null}` |
| LLM sends empty/missing `code` | `clientToolHandler` | `{"stdout": "", "error": "No code provided"}` |
| LLM sends unknown tool name | `clientToolHandler` | `{"stdout": "", "error": "Unknown client tool: ..."}` |
| Client silent >10 s | Server-side `asyncio.wait_for` in `_client_dispatcher` | `{"stdout": "", "error": "Tool execution timed out after 10000ms"}` |
| User fully disconnects during wait | `ClientToolDispatcher.cancel_for_user` from the WS manager | `{"stdout": "", "error": "Client disconnected before tool completed"}` |
| Foreign `tool_call_id` (user mismatch) | `ClientToolDispatcher.resolve` defence | Nothing resolved; warning logged; server timeout later catches it |
| Duplicate response to same id | `if not future.done()` | First wins, second silently ignored |
| Multi-tab race | Targeted fanout via `target_connection_id` | **Event reaches only the originating tab.** No duplicate executions. |

Budgets:

| Layer | Value | Location |
|---|---|---|
| Server wait (`asyncio.wait_for`) | 10 000 ms | `_CLIENT_TOOL_SERVER_TIMEOUT_MS` |
| Client Worker timeout | 5 000 ms | `_CLIENT_TOOL_CLIENT_TIMEOUT_MS`, passed via event |
| Network/scheduler buffer | = 5 000 ms difference | implicit |

### 5. Threat model

**Scenario A — user spoofs a result for their own pending tool call.**
Requires no attack: a user can always send `chat.client_tool.result` with
a matching `tool_call_id`. Effect: the user's own LLM sees a different
output than the JS actually produced. This changes nothing — the user
could already achieve the same effect by sending any user message. **No
additional attack surface.**

**Scenario B — user spoofs a result for another user's pending tool call.**
Requires the attacker to know the target's `tool_call_id` within the ~10 s
pending window. Tool-call IDs are cryptographically random strings
generated by the LLM SDK and are not otherwise exposed to other users or
logged in user-visible places. Practical attack feasibility is near zero.
The user-id check in `ClientToolDispatcher.resolve` is defence in depth:
cheap, guards against future accidental leakage, and improves debugging
clarity when a misrouted id is ever observed.

**Scenario C — prompt injection via tool output.** Out of scope for this
spec; this is a general LLM concern and applies equally to server-side
tool outputs (web search results, artefact contents). Not specific to
client-side tools.

**Scenario D — sandbox escape.** If Web Worker isolation were broken, the
whole web stack would be broken — this is a browser primitive, not a
Chatsune concern.

### 6. Testing

#### Backend unit tests (`pytest`)

1. **`ClientToolDispatcher.dispatch` happy path** — mock event bus, start
   dispatch coroutine in a task, call `resolve` with a fake result,
   assert the awaited value and that `_pending` is empty after return.
2. **`ClientToolDispatcher.dispatch` server timeout** — call with
   `timeout_ms=50` and never resolve; assert the synthetic timeout error
   result, assert `_pending` is empty.
3. **`ClientToolDispatcher.resolve` user mismatch** — register a pending
   future for user A, call `resolve` with `received_from_user_id=B`;
   assert the future is still pending and a warning was logged.
4. **`ClientToolDispatcher.cancel_for_user`** — start dispatch in a task,
   call `cancel_for_user(user_id)`; assert the synthetic disconnect error
   result is returned.
5. **`execute_tool` with `side="client"`** — mock the dispatcher, call
   `execute_tool` for `calculate_js`; assert `dispatch` was called with
   the expected kwargs and the return value propagates.
6. **`execute_tool` with `side="server"` regression** — existing tool
   (e.g. mocked `WebSearchExecutor`) still routes through the old path.
7. **Router handler for `chat.client_tool.result`** — well-formed payload
   triggers `resolve`; malformed payloads (missing fields, wrong types)
   are caught by Pydantic and only log a warning.
8. **Event bus targeted fanout** — publishing with `target_connection_id`
   delivers only to that connection; publishing without the parameter
   delivers to all of a user's connections. Regression-sensitive, because
   the fanout table is a core shared component.

#### Frontend unit tests (Vitest)

9. **`sandbox.worker.ts` smoke** — using Vitest's Worker support or a
   polyfill:
   - `console.log(2 + 2)` → `{stdout: "4", error: null}`
   - `console.log([...'erdbeere'].filter(c => c === 'r').length)` →
     `{stdout: "3", error: null}`
   - `throw new Error('boom')` → `{stdout: "", error: "Error: boom"}`
   - `fetch('https://evil.example')` → error result with `TypeError`
     (because `fetch === undefined`)
   - 10 000 × `console.log('x')` → `stdout` ≤ 4 KB and ends with
     `"... (output truncated)"`
10. **`sandboxHost.runSandbox` timeout** — pass `while(true){}`, verify
    the timeout path resolves with the synthetic timeout error and the
    Worker is terminated without leaking Promises.
11. **`clientToolHandler` missing-code guard** — a dispatch event without
    `arguments.code` produces an error result via `sendMessage` without
    calling `runSandbox`.

#### Manual end-to-end verification

Documented in the PR description; no automated E2E suite in Chatsune.

12. **Erdbeer meme** — new session, weak model (GLM/DeepSeek), prompt
    "Wie viele 'r' sind im Wort Erdbeere?"; model calls `calculate_js`,
    sees 3, answers 3.
13. **Exact arithmetic** — "Rechne mir 2^53 + 1 genau aus"; model uses
    `BigInt`, answers `9007199254740993`.
14. **JSON parsing** — "Aus `{\"a\":1,\"b\":[2,3]}`, zähle alle
    Zahlenwerte"; tool is used, correct count.
15. **Hard-stop failure** — direct prompt to call `calculate_js` with
    `code: "fetch('http://example.com')"`; the error result explains the
    network restriction.
16. **Toggle off** — disable `code_execution` in the session, repeat (12);
    the model does not call the tool and likely answers from
    tokens-alone (possibly incorrectly).
17. **Multi-tab** — open two tabs on the same session, send a message in
    tab 1; only tab 1 shows the tool-call activity indicator, tab 2
    remains silent.
18. **Disconnect during wait** — snippet that burns time
    (`for(let i=0;i<1e9;i++){}`), close the tab mid-execution; server
    logs show `"Client disconnected before tool completed"`, the inference
    loop finishes with an error result, no hang.

#### Not tested

- No performance or load tests — Worker-per-call creation is not the
  bottleneck for Phase 1.
- No sandbox fuzzing — Web Worker is a browser primitive.
- No automated E2E — Chatsune has no such suite; manual verification
  matches the existing project pattern.

---

## Implementation checklist

One line per step, ordered roughly as they should be executed. The
writing-plans skill will expand each into a concrete task.

**Shared contracts:**

1. Add `CHAT_CLIENT_TOOL_DISPATCH` to `shared/topics.py`.
2. Add `ChatClientToolDispatchEvent` to `shared/events/chat.py`.
3. Add `ClientToolResultDto` and `ClientToolResultPayload` to
   `shared/dtos/tools.py`.

**Backend core:**

4. Ensure `backend/ws/manager.py` assigns a stable `connection_id` per
   accepted connection, and expose it via the connection context passed
   to router handlers.
5. Communicate the assigned `connection_id` to the client as part of the
   existing handshake/hello event.
6. Extend `backend/ws/event_bus.py::publish()` with an optional
   `target_connection_id` parameter; teach the fanout to filter on it.
7. Register `CHAT_CLIENT_TOOL_DISPATCH` in `_FANOUT` (INS-011).
8. Write `backend/modules/tools/_client_dispatcher.py` with the
   `ClientToolDispatcher` class, including `dispatch`, `resolve`, and
   `cancel_for_user`.
9. Extend `backend/modules/tools/__init__.py::execute_tool` signature
   with `tool_call_id`, `session_id`, and `originating_connection_id`
   keyword arguments; add the `side == "client"` branch.
10. Export `get_client_dispatcher()` from the tools module public API.
11. Register the `code_execution` `ToolGroup` with `calculate_js` in
    `_registry.py::_build_groups`.

**Backend wiring:**

12. Thread `originating_connection_id` through the chat module entry
    points → orchestrator → inference runner → `execute_tool`.
13. Add the `chat.client_tool.result` inbound message handler in
    `backend/ws/router.py`, validating with `ClientToolResultDto`.
14. Wire `ClientToolDispatcher.cancel_for_user` into
    `backend/ws/manager.py`'s disconnect path (only when the last
    connection for that user drops).

**Frontend:**

15. Create `frontend/src/features/code-execution/sandbox.worker.ts` with
    the globals-strip, console-capture, byte-bounded output, indirect
    eval, and error handling.
16. Create `frontend/src/features/code-execution/sandboxHost.ts` with
    the `runSandbox` function, including the correct timeout-resolves-
    the-promise pattern.
17. Create `frontend/src/features/code-execution/clientToolHandler.ts`
    that subscribes to the dispatch event and sends back the result.
18. Register `clientToolHandler` at app startup in `App.tsx` (or the
    equivalent setup hook).

**Testing:**

19. Backend unit tests per §6.
20. Frontend unit tests per §6.
21. Manual E2E checklist per §6, documented in the PR.

**Build verification:**

22. `pnpm run build` clean.
23. `uv run python -m py_compile` on every changed backend file clean.
24. Existing tests still pass (regression sensitivity around
    `execute_tool` signature change).

---

## Open questions — none

All brainstorming questions answered. This spec is ready for the
writing-plans step.
