# Kimi K2.5 / K2.6 — wire-shape probes on Ollama Cloud and Novita

**Probed:** 2026-05-12
**Models:**

- Ollama Cloud: `kimi-k2.5`, `kimi-k2.6` (endpoint `https://ollama.com/api/chat`)
- Novita: `moonshotai/kimi-k2.5`, `moonshotai/kimi-k2.6`
  (endpoint `https://api.novita.ai/v3/openai/chat/completions`)

**Tool-roundtrip headline:** Kimi does **NOT** exhibit the MiMo-on-Novita
bug. The exact same wire shape that fails for `xiaomimimo/*` succeeds for
`moonshotai/kimi-k2.*` and for both Kimi slugs on Ollama Cloud.

---

## Per-(provider, slug) result table

| Provider | Slug | Basic chat | Reasoning behaviour | Tool emission | Tool-roundtrip |
|---|---|---|---|---|---|
| Ollama Cloud | `kimi-k2.5` | OK (200) | `optional` — `think: true` returns `message.thinking`; `think: false` returns `thinking: ""` | OK (`message.tool_calls[]`) | **OK (200)** |
| Ollama Cloud | `kimi-k2.6` | OK (200) | `optional` — same as K2.5: `think: true/false` honoured | OK (`message.tool_calls[]`) | **OK (200)** |
| Novita | `moonshotai/kimi-k2.5` | OK (200) | **No reasoning** — `reasoning_content` empty regardless of `reasoning.enabled`; K2.5 on Novita behaves like a non-reasoning model | OK (`choices[0].message.tool_calls[]`, `finish_reason: tool_calls`) | **OK (200)** |
| Novita | `moonshotai/kimi-k2.6` | OK (200) | **Always-on reasoning** — `reasoning_content` populated even with `reasoning: {enabled: false}` (and when the field is omitted entirely). K2.6 on Novita has no way to disable thinking. | OK (`choices[0].message.tool_calls[]`, `finish_reason: tool_calls`) | **OK (200)** |

### Capability summary

- **Reasoning capability** differs between providers for K2.5:
  - Ollama K2.5 + K2.6 → `reasoning.kind = "optional"` (driver should write
    `think: true/false` explicitly, mirroring the existing Ollama adapter
    rule).
  - Novita K2.5 → `reasoning.kind = "no_reasoning"`.
  - Novita K2.6 → `reasoning.kind = "always_on"` (or `"optional"` with a
    documented caveat that the toggle is ignored upstream; recommend
    `always_on` since the field is not honoured today).
- **Tool support** is safe on every (provider, slug): emission and
  continuation both work with the canonical OpenAI tool-call shape.

---

## Minimal working request bodies

### Ollama Cloud — K2.5 / K2.6 (identical shape)

Basic chat (non-streaming):

```json
{
  "model": "kimi-k2.5",
  "stream": false,
  "messages": [{"role": "user", "content": "Say hello in one word."}]
}
```

Reasoning on:

```json
{
  "model": "kimi-k2.5",
  "stream": false,
  "think": true,
  "messages": [{"role": "user", "content": "What is 17*23?"}]
}
```

Reasoning off (explicit, follows existing adapter rule):

```json
{
  "model": "kimi-k2.5",
  "stream": false,
  "think": false,
  "messages": [{"role": "user", "content": "What is 17*23?"}]
}
```

Tool emission:

```json
{
  "model": "kimi-k2.5",
  "stream": false,
  "messages": [{"role": "user", "content": "What is the weather in Berlin?"}],
  "tools": [{
    "type": "function",
    "function": {
      "name": "get_weather",
      "description": "Get current weather for a city",
      "parameters": {
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"]
      }
    }
  }]
}
```

Tool-call continuation (Ollama format — `arguments` is an **object**, not a
JSON string; `tool` message carries no `tool_call_id`):

```json
{
  "model": "kimi-k2.5",
  "stream": false,
  "messages": [
    {"role": "user", "content": "What is the weather in Berlin?"},
    {"role": "assistant", "content": "",
     "tool_calls": [
       {"function": {"name": "get_weather", "arguments": {"city": "Berlin"}}}
     ]},
    {"role": "tool", "content": "Sunny, 22°C"}
  ]
}
```

Response shape (non-streaming):

```json
{
  "model": "kimi-k2.5",
  "message": {
    "role": "assistant",
    "content": "Hello",
    "thinking": "The user wants me to say \"hello\"…"
  },
  "done": true,
  "done_reason": "stop",
  "prompt_eval_count": 14,
  "eval_count": 71
}
```

Tool-emission response:

```json
"message": {
  "role": "assistant",
  "content": "",
  "thinking": "…",
  "tool_calls": [
    {
      "id": "functions.get_weather:0",
      "function": {
        "index": 0,
        "name": "get_weather",
        "arguments": {"city": "Berlin"}
      }
    }
  ]
}
```

### Novita — `moonshotai/kimi-k2.5`

Basic chat (non-streaming, OpenAI-compat):

```json
{
  "model": "moonshotai/kimi-k2.5",
  "max_tokens": 50,
  "messages": [{"role": "user", "content": "Say hello in one word."}]
}
```

No reasoning toggle is honoured — `reasoning_content` is always empty on
K2.5. Omitting the `reasoning` field is the correct driver behaviour.

Tool emission:

```json
{
  "model": "moonshotai/kimi-k2.5",
  "max_tokens": 300,
  "messages": [{"role": "user", "content": "What is the weather in Berlin?"}],
  "tools": [{"type": "function", "function": { /* same as Ollama */ }}]
}
```

Tool-call continuation (the **MiMo-failing shape** — Kimi accepts it):

```json
{
  "model": "moonshotai/kimi-k2.5",
  "max_tokens": 300,
  "messages": [
    {"role": "user", "content": "What is the weather in Berlin?"},
    {"role": "assistant", "content": null,
     "tool_calls": [
       {"id": "call_xyz", "type": "function",
        "function": {"name": "get_weather", "arguments": "{\"city\":\"Berlin\"}"}}
     ]},
    {"role": "tool", "tool_call_id": "call_xyz", "content": "Sunny, 22°C"}
  ]
}
```

Returns HTTP 200 with `choices[0].message.content` populated. No
`reasoning_content` on the answer turn for K2.5.

### Novita — `moonshotai/kimi-k2.6`

Reasoning is always emitted. With or without `reasoning: {enabled: true}`
the response carries `choices[0].message.reasoning_content`. Setting
`reasoning: {enabled: false}` does **not** suppress it (verified —
`reasoning_content` was 521 chars long even with the toggle off).
Recommend treating K2.6 on Novita as `always_on` and not sending the
`reasoning` field at all.

Tool-call continuation succeeds with the same shape as K2.5. Response:

```json
"choices": [{"index": 0,
  "message": {"role": "assistant",
    "content": "The weather in Berlin is currently **sunny** with a temperature of **22°C**."},
  "finish_reason": "stop"}]
```

Note: on the tool-roundtrip answer turn K2.6 returned **no**
`reasoning_content` despite being an always-reasoning model — probably
because the answer is short and the chat template skipped the
`<think>` block. Driver should still treat it as `always_on` and not
rely on `reasoning_content` always being non-empty.

---

## Streaming chunk shape on Novita (matches DSv4-on-Novita)

### Basic content stream (K2.5)

```
data: {"choices":[{"index":0,"delta":{"content":"1","role":"assistant"},"finish_reason":null}], …}
data: {"choices":[{"index":0,"delta":{"content":","},"finish_reason":null}], …}
…
data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}], …}
data: {"choices":[],"usage":{"prompt_tokens":13,"completion_tokens":14,"total_tokens":27, …}}
data: [DONE]
```

### Reasoning stream (K2.6 — `delta.reasoning_content` chunks)

```
data: {"choices":[{"index":0,"delta":{"role":"assistant"}, …}]}
data: {"choices":[{"index":0,"delta":{"reasoning_content":"The"}, …}]}
data: {"choices":[{"index":0,"delta":{"reasoning_content":" user"}, …}]}
…
data: {"choices":[{"index":0,"delta":{},"finish_reason":"length"}, …]}
```

K2.6 emits a long block of `delta.reasoning_content` chunks first, then
(if not cut off by max_tokens) transitions to `delta.content` chunks for
the answer. The driver must treat `reasoning_content` ≠ `content`
exactly like DSv4 does on Novita.

### Tool-emission stream — OpenAI-fragmented (both K2.5 and K2.6)

First chunk announces the tool call (id + name), then `arguments` are
streamed as a series of string fragments under the same `index: 0`:

```
data: {"choices":[{"index":0,"delta":{"role":"assistant","tool_calls":[
  {"index":0,"id":"functions.get_weather:0","type":"function",
   "function":{"name":"get_weather"}}]}, …}]}
data: {"choices":[{"index":0,"delta":{"tool_calls":[
  {"index":0,"type":"function","function":{"arguments":"{\""}}]}, …}]}
data: {"choices":[{"index":0,"delta":{"tool_calls":[
  {"index":0,"type":"function","function":{"arguments":"city"}}]}, …}]}
data: {"choices":[{"index":0,"delta":{"tool_calls":[
  {"index":0,"type":"function","function":{"arguments":"\":"}}]}, …}]}
…
data: {"choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}, …]}
```

K2.6 additionally streams a short `delta.content` preamble ("I'll check
the weather in Berlin for you.") **before** the tool_calls chunks; K2.5
goes straight to tool_calls without a content preamble. The driver
already handles this for DSv4-on-Novita; same parser logic applies.

Tool-call IDs:

- K2.5 on Novita: `functions.get_weather:0` (dotted, colon-suffixed)
- K2.6 on Novita: `functions_get_weather_0` (underscore-joined)
- Ollama Cloud (both): `functions.get_weather:0`

These IDs need to be echoed verbatim on the continuation turn's
`assistant.tool_calls[].id` / `tool.tool_call_id` pair. None of the
formats triggered server-side validation issues.

---

## Comparison to the MiMo bug

| Test | MiMo-v2.5-pro on Novita | Kimi-k2.5 on Novita | Kimi-k2.6 on Novita |
|---|---|---|---|
| Single-turn tool emission | OK | OK | OK |
| Continuation with `assistant.tool_calls` + `tool` message | **400 (template bug)** | **200** | **200** |
| `assistant.content: null` + `tool_calls` populated | 400 | 200 | 200 |

Kimi's Novita chat template handles the inbound-`tool_calls` branch
correctly. This is consistent with Moonshot publishing the K2 tool-use
template upstream — Novita appears to have picked it up. No mitigation
needed, no special-case in the driver, no quarterly re-probe required.

---

## Recommendations

- **Tool capability** — safe to set `tools.supported = true` on both
  providers for both slugs. The MiMo-template bug is model-specific
  to the `xiaomimimo/*` family on Novita and does **not** affect Kimi.
- **Reasoning capability**:
  - Ollama K2.5, K2.6 → `reasoning.kind = "optional"`. Driver writes
    `think` explicitly (mirror existing `_ollama_http.py` rule).
  - Novita K2.5 → `reasoning.kind = "no_reasoning"`. Driver omits the
    `reasoning` field.
  - Novita K2.6 → `reasoning.kind = "always_on"`. Driver omits the
    `reasoning` field; UI should not expose a toggle because the
    upstream serving stack ignores it.
- **Streaming parser on Novita** — identical structure to DSv4-on-Novita
  (`delta.content`, `delta.reasoning_content`, OpenAI-fragmented
  `tool_calls`, final `finish_reason` + usage chunk + `[DONE]`).
  A driver that wraps the existing DSv4 Novita parser should work
  unchanged for Kimi on Novita.
- **Streaming parser on Ollama Cloud** — identical to existing
  `_ollama_http.py` NDJSON parsing (`message.content`,
  `message.thinking`, `message.tool_calls[]`, terminal `done: true` with
  `prompt_eval_count` / `eval_count`).

---

## Raw probe artefacts

All raw responses live under `/tmp/kimi-probes/` (probe machine only,
not checked in):

- `ollama_k25_basic.json`, `ollama_k26_basic.json` — basic chat
- `ollama_k25_reason_on.json`, `ollama_k25_reason_off.json`,
  `ollama_k26_reason_on.json`, `ollama_k26_reason_off.json`
- `ollama_k25_tool_emit.json`, `ollama_k26_tool_emit.json`
- `ollama_k25_tool_roundtrip.json`, `ollama_k26_tool_roundtrip.json`
- `novita_k25_basic.json`, `novita_k26_basic.json`
- `novita_k25_reason_on.json`, `novita_k25_reason_off.json`,
  `novita_k25_reason_none.json`, `novita_k26_reason_on.json`,
  `novita_k26_reason_off.json`, `novita_k26_reason_none.json`
- `novita_k25_tool_emit.json`, `novita_k26_tool_emit.json`
- `novita_k25_tool_roundtrip.json`, `novita_k26_tool_roundtrip.json`
- `novita_k25_stream.txt`, `novita_k26_stream.txt` — basic SSE
- `novita_k25_stream_tool.txt`, `novita_k26_stream_tool.txt` — tool-emit SSE
