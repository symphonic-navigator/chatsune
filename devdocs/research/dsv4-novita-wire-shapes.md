# DSv4 Novita — Wire-shape Research

**Probe date**: 2026-05-10
**Probed models**: DeepSeek V4 Pro and DeepSeek V4 Flash on Novita
**Endpoint**: `https://api.novita.ai/v3/openai/chat/completions`
**Purpose**: Capture the empirical baseline for the Plan 3 driver
implementation — effort vocabulary, CoT key, tool-call streaming, cache
visibility.

**Companion documents**:
- [`devdocs/research/deepseek-v4-wire-shapes.md`](deepseek-v4-wire-shapes.md) — base wire-shape research from Plan 1 (covers OR / nano-gpt / Novita / Ollama Cloud at a glance)
- [`devdocs/research/ollama-cloud-tool-calls.md`](ollama-cloud-tool-calls.md) — Ollama Cloud tool-call research from Plan 2
- [`devdocs/specs/driver-layer.md`](../specs/driver-layer.md) — Driver-Layer architecture

---

## Summary

Novita accepts `reasoning.effort` as **any string** without 400-rejection
— `"high"`, `"max"`, `"xhigh"`, `"invalid_xyz"` all returned 200. Unknown
values **silent-degrade** to default-low: `effort="invalid_xyz"` produced
roughly half the reasoning-tokens that `effort="high"` produced on the
same prompt. The driver validates client-side against `{high, max}` so a
typo or stale stored value surfaces as a loud `ValueError` instead of a
quiet quality drop.

CoT streams in `delta.reasoning_content` (DeepSeek-native), **not** OR's
`delta.reasoning`. Tool-call streaming is OpenAI-fragmented and indexed —
identical wire-shape to OR. Both Pro and Flash work on Novita with both
`{high, max}` buckets, so no router-quirk override is needed. The
terminal usage block carries `prompt_tokens_details.cached_tokens`,
giving Novita parity with OR for cache QA (nano-gpt does not expose this
field per existing memory).

**Driver implication**: the Novita parser reuses the
`ToolCallAccumulator` 1:1 from the OR side; the only diff vs OR is the
CoT key (`reasoning_content` vs `reasoning`).

---

## Probes

All eight probes used the same reasoning-fordernder prompt as the
Flash plan:

> "Finde drei strukturell verschiedene Beweise für die Unendlichkeit der
> Primzahlen…"

The two tool-call probes used the prompt:

> "Compare the weather in Berlin and Tokyo. Use the get_weather tool for
> both cities in the same turn."

### Reasoning-tokens summary

| Slug | effort | reasoning_tokens | Notes |
|---|---|---|---|
| Pro  | high      | 2250 | baseline |
| Pro  | max       | 2853 | +27%, works |
| Pro  | xhigh     | 2829 | ≈ max — accepted, silent-mapped to same internal mode |
| Pro  | invalid_xyz | 1403 | **silent-degraded** to default-low — no 400 error |
| Flash | high     | 1346 | baseline |
| Flash | max      | 1815 | +35%, works |
| Flash | xhigh    | 2047 | ≈ max — same as Pro |

(`invalid_xyz` only probed on Pro; Flash assumed to behave the same way
based on the consistent `xhigh ≈ max` behaviour across both buckets.)

---

## Probe A — Pro, effort=high

**Request body**:

```json
{
  "model": "deepseek/deepseek-v4-pro",
  "messages": [{"role": "user", "content": "Finde drei strukturell verschiedene Beweise für die Unendlichkeit der Primzahlen…"}],
  "stream": true,
  "stream_options": {"include_usage": true},
  "reasoning": {"enabled": true, "effort": "high"}
}
```

**Status**: 200

**Stream sample** (first reasoning chunk + terminal):

```
data: {"id":"chat-...","choices":[{"index":0,"delta":{"role":"assistant","reasoning_content":"Wir"}}]}
data: {"id":"chat-...","choices":[{"index":0,"delta":{"reasoning_content":" benötigen"}}]}
...
data: {"id":"chat-...","choices":[{"index":0,"delta":{"content":"Hier"}}]}
...
data: {"id":"chat-...","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":62,"completion_tokens":3574,"completion_tokens_details":{"reasoning_tokens":2250},"prompt_tokens_details":{"cached_tokens":0}}}
data: [DONE]
```

**Findings**:
- CoT streamed in `delta.reasoning_content` chunks (DeepSeek-native key).
  The OR-canonical `delta.reasoning` is **never** present on Novita.
- Visible content streams in `delta.content` after CoT completes.
- Terminal chunk: `finish_reason="stop"`, `usage` block carries
  `prompt_tokens`, `completion_tokens`,
  `completion_tokens_details.reasoning_tokens`, and
  `prompt_tokens_details.cached_tokens` (zero on cold prompt).
- `reasoning_tokens=2250` is the high-baseline.

---

## Probe B — Pro, effort=max

**Request body**: same as Probe A but `"effort": "max"`.

**Status**: 200

**Findings**:
- Identical wire-shape to Probe A.
- `reasoning_tokens=2853` — +27% over `high`. Effort is honoured.
- `prompt_tokens` stays at 62 (Novita does **not** inject an upstream
  system-prompt for `max`, unlike OR's `xhigh` path which jumps from
  19 → 98 tokens; see `deepseek-v4-wire-shapes.md` Probe Table).

---

## Probe C — Pro, effort=xhigh

**Request body**: same as Probe A but `"effort": "xhigh"`.

**Status**: 200 — accepted without 400.

**Findings**:
- Identical wire-shape to Probes A/B.
- `reasoning_tokens=2829` — within noise of `effort=max`'s 2853.
- Conclusion: Novita silently maps `xhigh` to the same internal mode as
  `max`. From the wire alone there is **no way to tell xhigh and max
  apart**. The driver rejects `xhigh` on the client side because (a) it
  is not in DeepSeek's canonical vocabulary and (b) it is indistinguishable
  from `max` server-side, so allowing it would just be a confusing alias.

---

## Probe D — Pro, effort=invalid_xyz

**Request body**: same as Probe A but `"effort": "invalid_xyz"`.

**Status**: 200 — accepted without 400.

**Findings**:
- `reasoning_tokens=1403` — substantially **lower** than `high`'s 2250.
- Conclusion: unknown effort values **silent-degrade** to a default-low
  setting. There is no error envelope, no warning header, no diagnostic
  hint that the value was unrecognised. This is the failure mode that
  drives the boundary-validation in the driver builder: a typo (`"hihg"`,
  `"maximum"`) or a stale stored value would silently halve the reasoning
  budget and the user would never know.

---

## Probe E — Flash, effort=high

**Request body**: same as Probe A but `"model": "deepseek/deepseek-v4-flash"`.

**Status**: 200

**Findings**:
- `reasoning_tokens=1346` — Flash's high-baseline. Lower than Pro at the
  same effort, as expected for the smaller model.
- Wire-shape identical to Pro: same CoT key, same usage block, same
  terminal chunk shape.

---

## Probe F — Flash, effort=max

**Request body**: same as Probe E but `"effort": "max"`.

**Status**: 200

**Findings**:
- `reasoning_tokens=1815` — +35% over Flash's `high`.
- Effort is honoured on Flash. Critical: **no Flash-quirk** here. On OR,
  `effort="max"` (which OR rewrites to `xhigh` upstream) **halves**
  Flash's reasoning instead of expanding it (see INS-041); on Novita the
  same logical effort produces the expected increase. No `_quirks.py`
  override is needed; capability spec stays at `["high","max"]` for the
  Novita+Flash pair.

---

## Probe G — Flash, effort=xhigh

**Request body**: same as Probe E but `"effort": "xhigh"`.

**Status**: 200

**Findings**:
- `reasoning_tokens=2047` — within noise of `effort=max`'s 1815, same
  pattern as Pro Probe C: silent-mapped to the same internal mode as
  `max`. Driver rejects on the client side.

---

## Probe H — Pro, tool-call stream (parallel get_weather)

**Request body** (reasoning on, parallel tool prompt):

```json
{
  "model": "deepseek/deepseek-v4-pro",
  "messages": [{"role": "user", "content": "Compare the weather in Berlin and Tokyo. Use the get_weather tool for both cities in the same turn."}],
  "stream": true,
  "stream_options": {"include_usage": true},
  "reasoning": {"enabled": true, "effort": "high"},
  "tools": [{
    "type": "function",
    "function": {
      "name": "get_weather",
      "description": "Get current weather for a city",
      "parameters": {
        "type": "object",
        "properties": {"city": {"type": "string", "description": "City name"}},
        "required": ["city"]
      }
    }
  }]
}
```

**Status**: 200

**Stream sample** (CoT first, then fragmented tool-calls, then terminal):

```
data: {"choices":[{"index":0,"delta":{"role":"assistant","reasoning_content":"Der"}}]}
... (many reasoning_content fragments) ...
data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"id":"call_00_IQTUKDOEICWC7THgQBYh0891","type":"function","function":{"name":"get_weather","arguments":""}}]}}]}
data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\""}}]}}]}
data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"city"}}]}}]}
data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\":\""}}]}}]}
data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"Berlin"}}]}}]}
data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\"}"}}]}}]}
data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":1,"id":"call_01_aB9C...","type":"function","function":{"name":"get_weather","arguments":""}}]}}]}
... (index=1 args fragments for "Tokyo") ...
data: {"choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}],"usage":{"prompt_tokens":303,"completion_tokens":102,"completion_tokens_details":{"reasoning_tokens":26},"prompt_tokens_details":{"cached_tokens":128}}}
data: [DONE]
```

**Findings**:
- **CoT-first ordering**: `delta.reasoning_content` chunks stream before
  any tool-call fragments. No interleaving.
- **OpenAI-fragmented tool-calls**: the first fragment per index carries
  `id` + `type` + `function.name` (with empty `function.arguments`);
  follow-on fragments add `function.arguments` as **string fragments**
  grouped by `index`. Parallel calls use distinct indices (0 and 1) and
  arrive sequentially per-index (all index=0 fragments first, then all
  index=1).
- **Tool-call ID shape**: `call_NN_AlphanumericTail` (e.g.
  `call_00_IQTUKDOEICWC7THgQBYh0891`) — Novita-internal format. The
  driver passes it through unchanged.
- **Terminal chunk co-emit**: `finish_reason="tool_calls"` arrives in
  the **same chunk** as the full `usage` block. The driver's parser must
  handle `ToolCallEvent` + `StreamDone` co-occurring on a single chunk
  (already covered by the OR parser; the Novita parser uses the same
  guard).
- **Cache visibility**: `prompt_tokens_details.cached_tokens=128` — Novita
  surfaces cached-token counts on tool-call iterations. OR does the same
  for DSv4. nano-gpt does not. When QA-ing cache-related features for
  DSv4, Novita is a viable alternative to OR.

---

## Wire-shape parity vs OpenRouter

| Aspect | OpenRouter | Novita |
|---|---|---|
| CoT stream key | `delta.reasoning` | `delta.reasoning_content` |
| CoT also carries `reasoning_details[]` | yes | no |
| Tool-call stream | OpenAI-fragmented, indexed | OpenAI-fragmented, indexed (identical) |
| Terminal `finish_reason` for tools | `"tool_calls"` | `"tool_calls"` (identical) |
| Usage co-emit on tool-call terminal | yes | yes (identical) |
| `completion_tokens_details.reasoning_tokens` | yes | yes |
| `prompt_tokens_details.cached_tokens` | yes | yes |
| Effort vocabulary at the wire | strict (400 on unknown) | permissive (silent-degrade) |
| Flash + max behaviour | broken on OR-`xhigh` (INS-041) | works as expected |

The only structural diff is the CoT key. Everything else carries over
1:1 — including the `ToolCallAccumulator`, which is shared between the
two parsers.
