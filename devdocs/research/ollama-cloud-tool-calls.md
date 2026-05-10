# Ollama Cloud — Tool-Call Wire-shape Research

**Probe date**: 2026-05-10
**Probed model**: DeepSeek V4 Pro on Ollama Cloud (`https://ollama.com/api/chat`)
**Purpose**: Decide whether the `DeepSeekV4Driver` Ollama parser needs streaming
tool-call accumulation (à la OpenRouter / OpenAI's `delta.tool_calls`) or
whether tool-calls arrive atomically in a single NDJSON chunk.

**Companion documents**:
- [`devdocs/research/deepseek-v4-wire-shapes.md`](deepseek-v4-wire-shapes.md) — base wire-shape research from Plan 1
- [`devdocs/specs/driver-layer.md`](../specs/driver-layer.md) — Driver-Layer architecture

---

## Summary

Ollama Cloud emits tool-calls **atomically** in a single NDJSON chunk —
**no incremental delta accumulation needed**. Multiple parallel tool-calls
arrive together as a list inside the same chunk's `message.tool_calls`.
The `done_reason` is always `"stop"` (never `"tool_calls"` like OpenAI), so
tool-call detection must be done by inspecting `message.tool_calls` directly,
not by branching on `done_reason`. When reasoning is on, thinking and
tool-calls are **sequential**: thinking streams across many chunks (one
fragment per chunk), then a single chunk delivers the entire tool-call
payload, then an empty chunk, then the terminal `done=true` chunk.

**Driver implication**: `parse_chunk_ollama_cloud` needs only a simple
per-chunk loop over `message.tool_calls` — no stateful accumulator like
`_ToolCallAccumulator` in the OpenRouter adapter. The `arguments` field is
a **Python dict** in the wire payload (not a JSON string), so the driver
must `json.dumps()` it to satisfy the `ToolCallEvent.arguments: str`
contract from `shared.dtos.inference`.

---

## Probe A — Single tool call, reasoning OFF

**Request body**:

```json
{
  "model": "deepseek-v4-pro",
  "messages": [{"role":"user","content":"What time is it in Tokyo? Use the get_time tool to find out."}],
  "stream": true,
  "think": false,
  "tools": [{
    "type": "function",
    "function": {
      "name": "get_time",
      "description": "Get the current time in a given timezone",
      "parameters": {
        "type": "object",
        "properties": {"timezone": {"type":"string","description":"IANA timezone name, e.g. Asia/Tokyo"}},
        "required": ["timezone"]
      }
    }
  }]
}
```

**Status**: 200
**Stream sample** (3 NDJSON lines total):

```
{"model":"deepseek-v4-pro","message":{"role":"assistant","content":"","tool_calls":[{"id":"call_5ysinpeh","function":{"index":0,"name":"get_time","arguments":{"timezone":"Asia/Tokyo"}}}]},"done":false}
{"model":"deepseek-v4-pro","message":{"role":"assistant","content":""},"done":false}
{"model":"deepseek-v4-pro","message":{"role":"assistant","content":""},"done":true,"done_reason":"stop","total_duration":1800715257,"prompt_eval_count":311,"eval_count":48}
```

**Findings**:
- Tool-call delivered **atomically** in chunk 1; chunks 2 and 3 carry no
  additional tool data.
- `tool_calls[0].id = "call_5ysinpeh"` — Ollama-generated, prefixed `call_`
  with 8 lowercase hex chars (similar but not identical to OpenAI's UUID
  shape). The driver should pass this through, not synthesise its own.
- `function.index = 0` lives **inside the function object**, not at the
  top of the tool-call entry (OpenAI puts `index` at the entry level).
  Curiosity, not blocker — the driver doesn't need it for atomic tool-calls.
- `function.arguments` is a **Python dict literal**, not a JSON string.
  The legacy adapter at `_ollama_http.py:558` already handles this with
  `json.dumps(fn.get("arguments", {}))` — the driver must do the same.
- `done_reason = "stop"` — **NOT `"tool_calls"`** as OpenAI does. Tool-call
  detection must inspect `message.tool_calls`, never `done_reason`.
- Token usage: `prompt_eval_count=311, eval_count=48`.

---

## Probe B — Multiple parallel tool calls

**Request body**: same shape as Probe A but prompting two cities:

```json
{
  "messages": [{"role":"user","content":"Compare the weather in Berlin and Tokyo. Use the get_weather tool for both cities in the same turn."}],
  "tools": [{"type":"function","function":{"name":"get_weather","description":"Get current weather for a city","parameters":{"type":"object","properties":{"city":{"type":"string","description":"City name"}},"required":["city"]}}}]
}
```

**Stream sample** (3 NDJSON lines total):

```
{"model":"deepseek-v4-pro","message":{"role":"assistant","content":"","tool_calls":[{"id":"call_iprdkyx2","function":{"index":0,"name":"get_weather","arguments":{"city":"Berlin"}}},{"id":"call_idgrvibj","function":{"index":1,"name":"get_weather","arguments":{"city":"Tokyo"}}}]},"done":false}
{"model":"deepseek-v4-pro","message":{"role":"assistant","content":""},"done":false}
{"model":"deepseek-v4-pro","message":{"role":"assistant","content":""},"done":true,"done_reason":"stop","total_duration":2924887414,"prompt_eval_count":302,"eval_count":76}
```

**Findings**:
- **Both tool-calls in the same chunk** — `tool_calls` is a length-2 list.
- Each entry has its own `id` and its own `function.index` (0 and 1).
- Same termination shape as Probe A: empty chunk + done chunk with
  `done_reason="stop"`.
- The driver's per-chunk loop will naturally emit two `ToolCallEvent`s
  back-to-back; no special branching needed.

---

## Probe C — Reasoning ON, tool-call follows thinking

**Request body**: same tool, but `"think": true` and a thinking-prompt:

```json
{
  "messages": [{"role":"user","content":"Think carefully step by step about what tool you should call to find out the weather in Tokyo, then call it."}],
  "stream": true,
  "think": true,
  "tools": [...same as Probe B...]
}
```

**Stream sample** (40 NDJSON lines total — first 5 + last 5 shown):

```
{"model":"deepseek-v4-pro","message":{"role":"assistant","content":"","thinking":"The"},"done":false}
{"model":"deepseek-v4-pro","message":{"role":"assistant","content":"","thinking":" user"},"done":false}
{"model":"deepseek-v4-pro","message":{"role":"assistant","content":"","thinking":" wants"},"done":false}
{"model":"deepseek-v4-pro","message":{"role":"assistant","content":"","thinking":" to"},"done":false}
{"model":"deepseek-v4-pro","message":{"role":"assistant","content":"","thinking":" know"},"done":false}
... [30 more thinking-fragment chunks omitted] ...
{"model":"deepseek-v4-pro","message":{"role":"assistant","content":"","thinking":"Tokyo"},"done":false}
{"model":"deepseek-v4-pro","message":{"role":"assistant","content":"","thinking":"\"."},"done":false}
{"model":"deepseek-v4-pro","message":{"role":"assistant","content":"","tool_calls":[{"id":"call_nlynysrr","function":{"index":0,"name":"get_weather","arguments":{"city":"Tokyo"}}}]},"done":false}
{"model":"deepseek-v4-pro","message":{"role":"assistant","content":""},"done":false}
{"model":"deepseek-v4-pro","message":{"role":"assistant","content":"","done":true,"done_reason":"stop","total_duration":7483929693,"prompt_eval_count":303,"eval_count":83}
```

**Findings**:
- Thinking and tool-calls are **sequential, not interleaved**: 38 chunks
  of thinking fragments (one word/punctuation per chunk), then a single
  chunk with the entire `tool_calls` payload, then empty + done.
- A chunk **never carries both** `message.thinking` AND
  `message.tool_calls` simultaneously. The driver does not need to handle
  that case.
- This is the exact wire-sequence that triggered the Plan-2 Bug 4
  ("Regenerate-Leiste fehlt nach Thinking-Abort"): the legacy driver
  parser dropped the `tool_calls` chunk silently; the stream proceeded to
  `done=true` with `done_reason="stop"`; `_inference.py` emitted
  `StreamDone` → `status="completed"`; the persisted message had
  `thinking != ""` but `content == ""`, and the frontend gate at
  `AssistantMessage.tsx:288` (pre-fix) hid the entire action bar. The
  Bug-4 fix (showing the bar when `thinking` is present) is defensive in
  depth; this driver-level fix removes the trigger.

---

## Implications for `parse_chunk_ollama_cloud`

Add tool-call extraction to the existing parser. Pattern mirrors the
legacy `_ollama_http.py:555-561` one-to-one:

```python
for tc in message.get("tool_calls", []):
    fn = tc.get("function") or {}
    events.append(ToolCallEvent(
        id=tc.get("id") or f"call_{uuid4().hex[:12]}",
        name=fn.get("name", ""),
        arguments=json.dumps(fn.get("arguments") or {}),
    ))
```

**Key correctness points**:
- `id` falls back to a synthetic UUID-ish only if Ollama omitted it
  (which it shouldn't, per probes — but defence in depth).
- `arguments` is `json.dumps()`-ed because the wire payload uses a dict
  while `ToolCallEvent.arguments` is `str`.
- The loop emits zero events when `tool_calls` is absent (the common case).
- No `_ToolCallAccumulator` needed — each chunk's tool_calls list is
  complete in itself.

**Test coverage to add**:
1. Single tool-call chunk → one `ToolCallEvent` emitted, with correct
   id/name/arguments-as-string.
2. Multiple parallel tool-calls in one chunk → multiple `ToolCallEvent`s
   in emission order.
3. Chunk with both `thinking` and (later) `tool_calls` should never
   happen per Probe C — but a sanity test that `thinking + content`
   chunks emit zero tool-call events is cheap and worth having.
4. `arguments` produced as `str` (not dict) — protects the contract
   against future regressions if someone "simplifies" the dump.

**Tests NOT needed** (probe-validated as impossible or out of scope):
- Streaming tool-call accumulation across chunks (doesn't happen).
- Interleaved thinking + tool-calls in the same chunk (doesn't happen).
- `done_reason="tool_calls"` handling (Ollama uses `"stop"` instead).
