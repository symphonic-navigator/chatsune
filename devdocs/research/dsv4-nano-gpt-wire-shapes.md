# DeepSeek V4 wire shapes — nano-gpt

**Probed:** 2026-05-10
**Endpoint:** `https://nano-gpt.com/api/v1/chat/completions`
**Models probed:** `deepseek/deepseek-v4-pro:thinking`, `deepseek/deepseek-v4-flash:thinking`

## Q1 — slug catalogue

`GET /v1/models` returns the following DSv4-related slugs:

```
deepseek/deepseek-v4-flash
deepseek/deepseek-v4-flash:thinking
deepseek/deepseek-v4-pro
deepseek/deepseek-v4-pro:thinking
deepseek/deepseek-v4-pro-cheaper
deepseek/deepseek-v4-pro-cheaper:thinking
TEE/deepseek-v4-pro
TEE/deepseek-v4-pro:thinking
```

The four `:thinking`-suffixed entries pair automatically with their non-suffixed
counterparts via the existing `_nano_gpt_catalog._detect_suffix` logic
(switching_mode = "slug"). The `model_id` exposed to chatsune is the
non-thinking slug; the thinking slug is selected at request time when
`reasoning_mode="on"` (`_nano_gpt_http.py:402-424`).

### First-class classification

We mark only the canonical `deepseek/deepseek-v4-{pro,flash}` family as
first-class. The other two upstream paths are intentionally not curated:

- `TEE/deepseek-v4-*` — TEE is an incomplete vLLM-derived deployment; quirks
  upstream are not worth chatsune support burden.
- `deepseek/deepseek-v4-*-cheaper` — routes via the Chinese DeepSeek upstream;
  privacy-first product stance keeps these visible (users may opt in) but
  off the curated/recommended path.

Both are still streamable via the regular nano-gpt adapter; they simply do
not receive the `first_class_support=True` UI signal.

## Q2 — reasoning wire-key

The default `/api/v1/chat/completions` endpoint streams reasoning in
`delta.reasoning` (OR-unified shape), with a parallel `delta.reasoning_details`
array carrying typed fragments. Example chunk fragment:

```json
{"choices":[{"index":0,"delta":{
  "reasoning":"We are",
  "reasoning_details":[{"type":"reasoning.text","text":"We are","format":"unknown","index":0}],
  "content":""
},"finish_reason":null}]}
```

The existing `_nano_gpt_http._chunk_to_events` (line ~188) already reads
`delta.reasoning` (and falls back to legacy `delta.reasoning_content`). No
parser change is needed for the driver to function on nano-gpt.

## Q3-Q4 — effort vocabulary and on/off signal

Skipped by product decision: nano-gpt is exposed as on/off only. The
existing slug-pair mechanism (`:thinking` suffix) is the canonical
on/off encoding; the driver's nano-gpt capability spec deliberately
publishes `effort=None` (no buckets) so the UI shows only the toggle.

## Q5 — Flash + reasoning health

`deepseek/deepseek-v4-flash:thinking` produces coherent reasoning text.
**Telemetry quirk:** the `usage.reasoning_tokens` field is consistently
`0` despite reasoning content being present in the stream. This is a
nano-gpt server-side bug (counter not populated); we ignore it.
The reasoning *content* is correct.

## Q6 — tool-call wire-shape

Atomic. A single chunk carries the full `tool_calls` array:

```json
{"choices":[{"index":0,"delta":{
  "tool_calls":[{
    "index":0,
    "id":"call_00_JFoVArF7Sywzl32dCDhh5437",
    "type":"function",
    "function":{
      "arguments":"{\"city\": \"Vienna\"}",
      "name":"get_weather"
    }
  }]
},"finish_reason":null}]}
```

Unlike OR / Novita, nano-gpt does not fragment tool-call arguments
across multiple chunks. The existing `_nano_gpt_http` accumulator handles
atomic delivery as a degenerate case (one fragment carrying the full args).

## Q7 — cache visibility

The `usage` block exposes `cached_tokens` and `cache_read_input_tokens`,
but both stayed at `0` in repeat-prompt probing. This is consistent with
the existing reference memory note: nano-gpt's *dashboard* shows no
cache split, and the API surface technically exposes the field but
appears not to populate it (or caching is not active for these requests).
For QA work that depends on cache validation visibility, OR remains the
preferred test path.

---

## Driver implications

This driver is a **capability-only extension**:

- Capability spec (`deepseek_v4_capability_spec`) gains a
  `nano_gpt_http` branch that emits `kind=optional`, `effort=None`,
  `default_on=True`, and a slug-classifier-derived
  `first_class_support` boolean.
- `DeepSeekV4Driver.build_request` / `parse_chunk` continue to raise
  `NotImplementedError` for `nano_gpt_http` — by design. The nano-gpt
  adapter's existing wire-shape handling is sufficient.
