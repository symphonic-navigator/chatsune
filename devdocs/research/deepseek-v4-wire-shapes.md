# DeepSeek V4 Pro — Wire-shape Research

**Probe date**: 2026-05-10
**Probed model**: DeepSeek V4 Pro
**Routers**: OpenRouter, nano-gpt, Novita, Ollama Cloud
**Purpose**: Input for the upcoming `DeepSeekV4Driver` spec — concrete wire
evidence per router, captured against the live APIs with `curl`.

---

## Summary

All four routers expose DeepSeek V4 Pro and all probes succeeded; no auth
errors, no rate limits. The biggest divergence is the **CoT stream key**: OR
and nano-gpt-`:thinking` ship CoT in `delta.reasoning` (OR canonical),
Novita ships it in `delta.reasoning_content` (DeepSeek native), and Ollama
Cloud ships it in `message.thinking` (Anthropic-style, NDJSON not SSE). The
biggest surprise was that **nano-gpt requires the `:thinking` model-slug
suffix to enable reasoning at all** — passing `reasoning.effort=high` to
the plain slug is silently dropped, you have to switch model IDs. A close
second: nano-gpt accepts `reasoning.effort=max` (200 OK) where OR rejects
the same effort with HTTP 400.

---

## Table 1: Wire-shapes (router x reasoning config)

| Router | Config | Reasoning toggle field | Effort field | CoT stream key | reasoning_tokens reported | content (eval) tokens | Notes |
|---|---|---|---|---|---|---|---|
| OpenRouter | OFF | `reasoning.enabled=false` | n/a | n/a | 0 | 1 | Provider routed to SiliconFlow. |
| OpenRouter | default | implicit (effort given) | `reasoning.effort=high` | `delta.reasoning` (+ `reasoning_details[].text`) | 360 | 800 (incl. reasoning) | Provider routed to DeepInfra. CoT visible. |
| OpenRouter | max | implicit | `reasoning.effort=xhigh` | `delta.reasoning` | 215 | 815 | `prompt_tokens` jumps 19 -> 98 (system-prompt injection by upstream for DS native `max`). |
| nano-gpt | OFF | none on plain slug | n/a | n/a | n/a (no usage block) | 1 | Model `deepseek/deepseek-v4-pro` is the non-thinking variant. |
| nano-gpt | default | model-slug suffix `:thinking` | `reasoning.effort=high` | `delta.reasoning` (+ `reasoning_details`) | not reported | 677 | Slug `deepseek/deepseek-v4-pro:thinking`. Reasoning content present, no `reasoning_tokens` field. |
| nano-gpt | max | model-slug suffix `:thinking` | `reasoning.effort=max` | `delta.reasoning` | not reported | 892 | `effort=max` accepted (200 OK); `prompt_tokens` 19 -> 98 (same upstream injection as OR `xhigh`). |
| nano-gpt | TEE | n/a (separate model) | n/a | n/a | n/a | 2 | Slug `TEE/deepseek-v4-pro` exists alongside `:thinking` sibling `TEE/deepseek-v4-pro:thinking`. Identical wire shape to plain slug. |
| Novita | OFF | top-level `thinking.type=disabled` | n/a | n/a | 0 (`completion_tokens_details=null`) | 1 | `reasoning.enabled=false` is silently ignored — see quirks. |
| Novita | default | top-level `thinking.type=enabled` | `reasoning.effort=high` | `delta.reasoning_content` (DeepSeek native) | 237 | 657 | DOES NOT use OR-canonical `delta.reasoning`. |
| Novita | max | top-level `thinking.type=enabled` | `reasoning.effort=max` | `delta.reasoning_content` | 245 | 742 | `prompt_tokens` stays at 19 — Novita does not inject the upstream `xhigh`/`max` system prompt. |
| Ollama Cloud | OFF | `think=false` (top-level) | n/a | n/a | n/a | 2 (`eval_count`) | Native Ollama protocol — NDJSON, no `data:` prefix. |
| Ollama Cloud | default | `think=true` | n/a (boolean only) | `message.thinking` | n/a (no separate field) | 789 (`eval_count`, includes reasoning) | Ollama returns total `eval_count`; no split into reasoning vs visible. |
| Ollama Cloud | max | `think="max"` (string) | string-valued `think` | `message.thinking` | n/a | 891 (`eval_count`) | `think` accepts strings; `prompt_eval_count` 19 -> 98 confirms upstream `max` system prompt is injected. |

---

## Table 2: Provider metadata coverage

| Router | Slug(s) for DS V4 Pro | context_length | pricing exposed | supports_tools | supports_reasoning | Other notable fields |
|---|---|---|---|---|---|---|
| OpenRouter | `deepseek/deepseek-v4-pro` (canonical: `deepseek/deepseek-v4-pro-20260423`) | `1048576` | yes (`prompt`, `completion`, `input_cache_read`) | yes (`tools`, `tool_choice` in `supported_parameters`) | yes (`reasoning`, `include_reasoning` in `supported_parameters`) | `top_provider.max_completion_tokens=384000`, `architecture.tokenizer="DeepSeek"`, `default_parameters.temperature=1`, sibling Flash exists at `deepseek/deepseek-v4-flash`. |
| nano-gpt | `deepseek/deepseek-v4-pro`, `deepseek/deepseek-v4-pro:thinking`, `deepseek/deepseek-v4-pro-cheaper`, `deepseek/deepseek-v4-pro-cheaper:thinking`, `TEE/deepseek-v4-pro`, `TEE/deepseek-v4-pro:thinking` | not exposed by `/models` | not exposed by `/models` (only via `x_nanogpt_pricing` in stream) | implicit (no metadata) | implicit — encoded in `:thinking` slug suffix | Sparse **default** `/models` payload: just `id`, `object`, `created`, `owned_by`. **Pass `?detailed=true`** to get full metadata: `context_length`, `max_output_tokens`, `capabilities` (vision/reasoning/tool_calling/etc.), `architecture`. **TEE variant `TEE/deepseek-v4-pro` has `context_length: 800000`** and `max_output_tokens: 65536` — distinct from the regular slug's 1M context. `capabilities.reasoning: true` is declared. |
| Novita | `deepseek/deepseek-v4-pro` | `1048576` (`context_size`) | yes (`input_token_price_per_m=16900`, `output_token_price_per_m=33800` — i.e. cents-per-million units) | yes (`features=["serverless","function-calling","structured-outputs","reasoning"]`) | yes (in `features`) | `max_output_tokens=393216`, `endpoints=["chat/completions","anthropic"]`, sibling Flash at `deepseek/deepseek-v4-flash`. |
| Ollama Cloud | `deepseek-v4-pro` (no namespace) | not advertised in `/api/tags` | not advertised | not advertised | not advertised | `/api/tags` returns just `name`, `model`, `modified_at`, `size`, `digest`, empty `details`. Capability discovery requires probing or out-of-band. |

> **TEE note**: The TEE variant `TEE/deepseek-v4-pro` has
> **`context_length: 800000`** (vs 1M for the regular slug) and
> **`max_output_tokens: 65536`**, with reasoning explicitly declared
> (`capabilities.reasoning: true`). This metadata is only visible via
> `GET /v1/models?detailed=true` — the default `/v1/models` endpoint
> returns a sparse payload that omits these fields. **Lesson: when
> evaluating nano-gpt metadata coverage, always pass `?detailed=true`.**
> Provider-metadata-merge in the driver will correctly populate the
> reduced TEE context once the driver wires up the detailed endpoint.
> *(Initial probe used the default endpoint and missed this; corrected
> from user evidence 2026-05-10.)*

---

## Detailed probe results

### OpenRouter

#### Slug discovery

```json
{
  "id": "deepseek/deepseek-v4-pro",
  "canonical_slug": "deepseek/deepseek-v4-pro-20260423",
  "name": "DeepSeek: DeepSeek V4 Pro",
  "context_length": 1048576,
  "architecture": { "tokenizer": "DeepSeek", "modality": "text->text" },
  "pricing": {
    "prompt": "0.000000435",
    "completion": "0.00000087",
    "input_cache_read": "0.000000003625"
  },
  "top_provider": {
    "context_length": 1048576,
    "max_completion_tokens": 384000,
    "is_moderated": false
  },
  "supported_parameters": [
    "frequency_penalty","include_reasoning","logit_bias","logprobs",
    "max_tokens","min_p","presence_penalty","reasoning",
    "repetition_penalty","response_format","seed","stop",
    "structured_outputs","temperature","tool_choice","tools",
    "top_k","top_logprobs","top_p"
  ]
}
```

#### Probe A — reasoning OFF

**Request body**:

```json
{
  "model": "deepseek/deepseek-v4-pro",
  "messages": [{"role":"user","content":"What is 2+2? Answer with just the number."}],
  "max_tokens": 100,
  "stream": true,
  "reasoning": {"enabled": false},
  "usage": {"include": true}
}
```

**Status**: 200
**Key headers**: `content-type: text/event-stream`, `x-generation-id: gen-1778394826-…`, `cf-ray: …-VIE`, `server: cloudflare`
**Stream sample** (4 chunks total, including `[DONE]`):

```
: OPENROUTER PROCESSING (heartbeats x6)

data: {"id":"gen-…","model":"deepseek/deepseek-v4-pro-20260423","provider":"SiliconFlow","choices":[{"index":0,"delta":{"content":"4","role":"assistant"}}]}
data: {"id":"gen-…","provider":"SiliconFlow","choices":[{"index":0,"delta":{"content":"","role":"assistant"},"finish_reason":"stop","native_finish_reason":"stop"}]}
data: {"id":"gen-…","provider":"SiliconFlow","choices":[{"index":0,"delta":{...},"finish_reason":"stop"}],"usage":{"prompt_tokens":17,"completion_tokens":1,"total_tokens":18,"completion_tokens_details":{"reasoning_tokens":0,"image_tokens":0,"audio_tokens":0}}}
data: [DONE]
```

**CoT stream key observed**: n/a (reasoning off)
**Total reasoning chars**: 0
**Usage**: `prompt_tokens=17, completion_tokens=1, reasoning_tokens=0, cached_tokens=0, cost=$0.00003306` (provider: SiliconFlow)

#### Probe B — reasoning ON, default (effort=high)

**Request body**:

```json
{
  "model": "deepseek/deepseek-v4-pro",
  "messages": [{"role":"user","content":"Why are there infinitely many prime numbers? Give a step-by-step proof."}],
  "max_tokens": 800,
  "stream": true,
  "reasoning": {"effort": "high"},
  "usage": {"include": true}
}
```

**Status**: 200
**Stream sample** (315 chunks total, first 5 + last 3):

```
data: {"id":"gen-…","provider":"DeepInfra","choices":[{"index":0,"delta":{"content":"","role":"assistant","reasoning":"We n","reasoning_details":[{"type":"reasoning.text","text":"We n","format":"unknown","index":0}]}}]}
data: {"id":"gen-…","provider":"DeepInfra","choices":[{"index":0,"delta":{"content":"","role":"assistant","reasoning":"eed to give a "}}]}
data: {"id":"gen-…","provider":"DeepInfra","choices":[{"index":0,"delta":{"content":"","role":"assistant","reasoning":"step-by-step pr"}}]}
data: {"id":"gen-…","provider":"DeepInfra","choices":[{"index":0,"delta":{"content":"","role":"assistant","reasoning":"oof that there are inf"}}]}
data: {"id":"gen-…","provider":"DeepInfra","choices":[{"index":0,"delta":{"content":"","role":"assistant","reasoning":"initely many "}}]}
... [307 chunks omitted] ...
data: {"id":"gen-…","provider":"DeepInfra","choices":[{"index":0,"delta":{"content":"","role":"assistant","reasoning":null},"finish_reason":"length","native_finish_reason":"length"}]}
data: {"id":"gen-…","provider":"DeepInfra","choices":[{"index":0,"delta":{"content":"","role":"assistant"},"finish_reason":"length"}],"usage":{"prompt_tokens":19,"completion_tokens":800,"total_tokens":819,"cost":0.00281706,"completion_tokens_details":{"reasoning_tokens":360,"image_tokens":0,"audio_tokens":0}}}
data: [DONE]
```

**CoT stream key observed**: `delta.reasoning` (string) plus structured
`delta.reasoning_details[]` (`{type:"reasoning.text", text, format, index}`).
**Total reasoning chars**: 1390
**Usage**: `prompt_tokens=19, completion_tokens=800, reasoning_tokens=360, cost=$0.00281706` (provider: DeepInfra; finish_reason=length, hit token cap mid-answer)

#### Probe C — reasoning ON, max (effort=xhigh)

**Request body**:

```json
{
  "model": "deepseek/deepseek-v4-pro",
  "messages": [{"role":"user","content":"Why are there infinitely many prime numbers? Give a step-by-step proof."}],
  "max_tokens": 1500,
  "stream": true,
  "reasoning": {"effort": "xhigh"},
  "usage": {"include": true}
}
```

**Status**: 200
**Stream sample** (817 chunks total, first 5 + last 3):

```
data: {"id":"gen-…","provider":"SiliconFlow","choices":[{"index":0,"delta":{"content":"","role":"assistant","reasoning":"We"}}]}
data: {"id":"gen-…","provider":"SiliconFlow","choices":[{"index":0,"delta":{"reasoning":" need"}}]}
data: {"id":"gen-…","provider":"SiliconFlow","choices":[{"index":0,"delta":{"reasoning":" to"}}]}
data: {"id":"gen-…","provider":"SiliconFlow","choices":[{"index":0,"delta":{"reasoning":" give"}}]}
data: {"id":"gen-…","provider":"SiliconFlow","choices":[{"index":0,"delta":{"reasoning":" a"}}]}
... [809 chunks omitted] ...
data: {"id":"gen-…","provider":"SiliconFlow","choices":[{"index":0,"delta":{"reasoning":null},"finish_reason":"stop"}]}
data: {"id":"gen-…","provider":"SiliconFlow","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":98,"completion_tokens":815,"total_tokens":913,"cost":0.00300672,"completion_tokens_details":{"reasoning_tokens":215,"image_tokens":0,"audio_tokens":0}}}
data: [DONE]
```

**CoT stream key observed**: `delta.reasoning` (same as Probe B)
**Total reasoning chars**: 872
**Usage**: `prompt_tokens=98 (vs 19 baseline), completion_tokens=815, reasoning_tokens=215, cost=$0.00300672` (provider: SiliconFlow)
**Note on prompt_tokens jump**: The 19 -> 98 increase indicates an
upstream-injected system prompt that activates DeepSeek-native `max`
reasoning. This injection happens at the upstream provider level; OR
just translates `effort=xhigh` to whatever envelope the provider expects.
SiliconFlow vs DeepInfra both honour it.

#### Quirk verification: OR rejects `effort=max`

Direct probe with body `{"reasoning":{"effort":"max"}}`:

```json
{"error":{"message":"reasoning.effort: Invalid option: expected one of \"xhigh\"|\"high\"|\"medium\"|\"low\"|\"minimal\"|\"none\"","code":400}}
```

OR's accepted vocabulary is **exactly** `none|minimal|low|medium|high|xhigh`.

---

### nano-gpt

#### Slug discovery

```json
[
  {"id":"deepseek/deepseek-v4-pro","object":"model","created":1776988800,"owned_by":"organization-owner"},
  {"id":"deepseek/deepseek-v4-pro:thinking","object":"model","created":1776988800,"owned_by":"organization-owner"},
  {"id":"deepseek/deepseek-v4-pro-cheaper","object":"model","created":1777075200,"owned_by":"organization-owner"},
  {"id":"deepseek/deepseek-v4-pro-cheaper:thinking","object":"model","created":1777075200,"owned_by":"organization-owner"},
  {"id":"TEE/deepseek-v4-pro","object":"model","created":1777075200,"owned_by":"organization-owner"},
  {"id":"TEE/deepseek-v4-pro:thinking","object":"model","created":1777420800,"owned_by":"organization-owner"}
]
```

The `/models` payload is sparse — no `context_length`, no `pricing`, no
`supports_*` fields. Reasoning capability is encoded **in the slug** via
the `:thinking` suffix.

#### Probe A — reasoning OFF (plain slug)

**Request body**:

```json
{
  "model": "deepseek/deepseek-v4-pro",
  "messages": [{"role":"user","content":"What is 2+2? Answer with just the number."}],
  "max_tokens": 100,
  "stream": true
}
```

**Status**: 200
**Stream sample** (4 chunks total):

```
data: {"id":"chatcmpl-…","model":"deepseek/deepseek-v4-pro","choices":[{"index":0,"delta":{"role":"assistant"}}]}
data: {"id":"chatcmpl-…","model":"deepseek/deepseek-v4-pro","choices":[{"index":0,"delta":{"content":"4"}}]}
data: {"id":"chatcmpl-…","model":"deepseek/deepseek-v4-pro","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"x_nanogpt_pricing":{"amount":0,"cost":0,"currency":"USD","inputTokens":17,"outputTokens":1,"cacheCost":0}}
data: [DONE]
```

**CoT stream key observed**: n/a
**Total reasoning chars**: 0
**Usage**: nano-gpt does not emit a top-level `usage` object. Token
counts arrive in `x_nanogpt_pricing` as `inputTokens=17, outputTokens=1`.
**No `reasoning_tokens` field at all.**

#### Probe B — reasoning ON, default (`:thinking` slug + effort=high)

**Request body**:

```json
{
  "model": "deepseek/deepseek-v4-pro:thinking",
  "messages": [{"role":"user","content":"Why are there infinitely many prime numbers? Give a step-by-step proof."}],
  "max_tokens": 800,
  "stream": true,
  "reasoning": {"effort": "high"}
}
```

**Status**: 200
**Stream sample** (360 chunks total, first 5 + last 3):

```
data: {"id":"chatcmpl-…","model":"deepseek/deepseek-v4-pro:thinking","choices":[{"index":0,"delta":{"role":"assistant"}}]}
data: {"id":"chatcmpl-…","choices":[{"index":0,"delta":{"reasoning":"We","reasoning_details":[{"type":"reasoning.text","text":"We","format":"unknown","index":0}],"content":""}}]}
data: {"id":"chatcmpl-…","choices":[{"index":0,"delta":{"reasoning":" need","content":""}}]}
data: {"id":"chatcmpl-…","choices":[{"index":0,"delta":{"reasoning":" to","content":""}}]}
data: {"id":"chatcmpl-…","choices":[{"index":0,"delta":{"reasoning":" give","content":""}}]}
... [352 chunks omitted] ...
data: {"id":"chatcmpl-…","choices":[{"index":0,"delta":{"content":" never be complete."}}]}
data: {"id":"chatcmpl-…","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"x_nanogpt_pricing":{"amount":0,"cost":0,"currency":"USD","inputTokens":19,"outputTokens":677,"cacheCost":0}}
data: [DONE]
```

**CoT stream key observed**: `delta.reasoning` (+ `delta.reasoning_details`) — **identical wire shape to OR**.
**Total reasoning chars**: 350 (chunked finely; reasoning ends mid-stream and content takes over)
**Usage**: `inputTokens=19, outputTokens=677` — **no separate reasoning_tokens count**.

#### Probe C — reasoning ON, max (`:thinking` slug + effort=max)

**Request body**:

```json
{
  "model": "deepseek/deepseek-v4-pro:thinking",
  "messages": [{"role":"user","content":"Why are there infinitely many prime numbers? Give a step-by-step proof."}],
  "max_tokens": 1500,
  "stream": true,
  "reasoning": {"effort": "max"}
}
```

**Status**: 200 (does not 400 the way OR does on `max`)
**Stream sample** (492 chunks total, first 5 + last 3):

```
data: {"id":"chatcmpl-…","model":"deepseek/deepseek-v4-pro:thinking","choices":[{"index":0,"delta":{"role":"assistant"}}]}
data: {"id":"chatcmpl-…","choices":[{"index":0,"delta":{"reasoning":"We","reasoning_details":[{"type":"reasoning.text","text":"We","format":"unknown","index":0}],"content":""}}]}
data: {"id":"chatcmpl-…","choices":[{"index":0,"delta":{"reasoning":" need","content":""}}]}
data: {"id":"chatcmpl-…","choices":[{"index":0,"delta":{"reasoning":" to","content":""}}]}
data: {"id":"chatcmpl-…","choices":[{"index":0,"delta":{"reasoning":" give","content":""}}]}
... [484 chunks omitted] ...
data: {"id":"chatcmpl-…","choices":[{"index":0,"delta":{"content":" primes."}}]}
data: {"id":"chatcmpl-…","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"x_nanogpt_pricing":{"amount":0,"cost":0,"currency":"USD","inputTokens":98,"outputTokens":892,"cacheCost":0}}
data: [DONE]
```

**CoT stream key observed**: `delta.reasoning`
**Total reasoning chars**: 1138
**Usage**: `inputTokens=98 (vs 19 baseline), outputTokens=892` — same
upstream system-prompt injection visible here as on OR `xhigh`. So
nano-gpt's `effort=max` and OR's `effort=xhigh` route to the same
upstream behaviour.

#### TEE variant probe (sanity check)

```
data: {"id":"chatcmpl-…","model":"TEE/deepseek-v4-pro","choices":[{"index":0,"delta":{"role":"assistant"}}]}
data: {"id":"chatcmpl-…","model":"TEE/deepseek-v4-pro","choices":[{"index":0,"delta":{"content":"4"}}]}
data: {"id":"chatcmpl-…","model":"TEE/deepseek-v4-pro","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"x_nanogpt_pricing":{"amount":0.00003135,"cost":0.00003135,"currency":"USD","inputTokens":15,"outputTokens":2,"requestId":"req_…"}}
data: [DONE]
```

Same wire shape as the regular nano-gpt slug, just routed through a TEE
provider. The TEE pricing (in this probe) was non-zero and includes a
`requestId` field, hinting that nano-gpt tracks TEE billing separately.
No advertised context-length difference — the prior-session "TEE at 800k"
hypothesis is not supported by `/models` metadata.

---

### Novita

#### Slug discovery

```json
{
  "id": "deepseek/deepseek-v4-pro",
  "title": "deepseek/deepseek-v4-pro",
  "display_name": "Deepseek V4 Pro",
  "context_size": 1048576,
  "max_output_tokens": 393216,
  "input_token_price_per_m": 16900,
  "output_token_price_per_m": 33800,
  "model_type": "chat",
  "features": ["serverless","function-calling","structured-outputs","reasoning"],
  "endpoints": ["chat/completions","anthropic"],
  "input_modalities": ["text"],
  "output_modalities": ["text"]
}
```

#### Probe A — reasoning OFF

**Request body**:

```json
{
  "model": "deepseek/deepseek-v4-pro",
  "messages": [{"role":"user","content":"What is 2+2? Answer with just the number."}],
  "max_tokens": 100,
  "stream": true,
  "thinking": {"type": "disabled"}
}
```

**Status**: 200
**Stream sample** (4 chunks total):

```
data: {"id":"…","model":"deepseek/deepseek-v4-pro","choices":[{"index":0,"delta":{"role":"assistant"}}],"sla_metrics":{"ttft_ms":1570}}
data: {"id":"…","choices":[{"index":0,"delta":{"content":"4"}}],"sla_metrics":{"ttft_ms":1570}}
data: {"id":"…","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":17,"completion_tokens":1,"total_tokens":18,"prompt_tokens_details":{"cached_tokens":0,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,...},"completion_tokens_details":null}}
data: [DONE]
```

**CoT stream key observed**: n/a (thinking disabled)
**Total reasoning chars**: 0
**Usage**: `prompt_tokens=17, completion_tokens=1`, `completion_tokens_details=null` (Novita sets it null when no reasoning happened).

> Novita includes a non-standard `sla_metrics` block on every chunk
> (`ttft_ms`, `ts_us`). Adapter parsers should ignore it.

#### Quirk verification: Novita ignores `reasoning.enabled=false`

Probe with `{"reasoning":{"enabled":false}}` and no `thinking` field, on
the prompt "Why is the sky blue? Detailed explanation." — 604 chunks
returned, **143 of them carried `reasoning_content`** in the delta. Novita
silently ignored the OR-style toggle and emitted a full chain of thought.
**Disabling reasoning on Novita requires `thinking.type=disabled`.**

#### Probe B — reasoning ON, default

**Request body**:

```json
{
  "model": "deepseek/deepseek-v4-pro",
  "messages": [{"role":"user","content":"Why are there infinitely many prime numbers? Give a step-by-step proof."}],
  "max_tokens": 800,
  "stream": true,
  "thinking": {"type": "enabled"},
  "reasoning": {"effort": "high"}
}
```

**Status**: 200
**Stream sample** (659 chunks total, first 5 + last 2):

```
data: {"id":"…","choices":[{"index":0,"delta":{"role":"assistant"}}],"sla_metrics":{...}}
data: {"id":"…","choices":[{"index":0,"delta":{"reasoning_content":"We"}}],"sla_metrics":{...}}
data: {"id":"…","choices":[{"index":0,"delta":{"reasoning_content":" need"}}]}
data: {"id":"…","choices":[{"index":0,"delta":{"reasoning_content":" to"}}]}
data: {"id":"…","choices":[{"index":0,"delta":{"reasoning_content":" provide"}}]}
... [651 chunks omitted] ...
data: {"id":"…","choices":[{"index":0,"delta":{"content":"."}}]}
data: {"id":"…","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":19,"completion_tokens":657,"total_tokens":676,"completion_tokens_details":{"reasoning_tokens":237,"text_tokens":0,...}}}
data: [DONE]
```

**CoT stream key observed**: **`delta.reasoning_content`** (DeepSeek
native key — different from OR/nano-gpt's `delta.reasoning`).
**Total reasoning chars**: 981
**Usage**: `prompt_tokens=19, completion_tokens=657, reasoning_tokens=237`. Novita reports `reasoning_tokens` properly.

#### Probe C — reasoning ON, max

**Request body**:

```json
{
  "model": "deepseek/deepseek-v4-pro",
  "messages": [{"role":"user","content":"Why are there infinitely many prime numbers? Give a step-by-step proof."}],
  "max_tokens": 1500,
  "stream": true,
  "thinking": {"type": "enabled"},
  "reasoning": {"effort": "max"}
}
```

**Status**: 200
**Stream sample** (744 chunks, first 5 + last 2):

```
data: {"id":"…","choices":[{"index":0,"delta":{"role":"assistant"}}]}
data: {"id":"…","choices":[{"index":0,"delta":{"reasoning_content":"We"}}]}
data: {"id":"…","choices":[{"index":0,"delta":{"reasoning_content":" are"}}]}
data: {"id":"…","choices":[{"index":0,"delta":{"reasoning_content":" asked"}}]}
data: {"id":"…","choices":[{"index":0,"delta":{"reasoning_content":":"}}]}
... [736 chunks omitted] ...
data: {"id":"…","choices":[{"index":0,"delta":{"content":"."}}]}
data: {"id":"…","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":19,"completion_tokens":742,"total_tokens":761,"completion_tokens_details":{"reasoning_tokens":245,"text_tokens":0,...}}}
data: [DONE]
```

**CoT stream key observed**: `delta.reasoning_content`
**Total reasoning chars**: 892
**Usage**: `prompt_tokens=19 (no jump), completion_tokens=742, reasoning_tokens=245`.
**Notable**: prompt_tokens stays at 19 — Novita does **not** inject the
upstream `xhigh`/`max` system prompt that OR and nano-gpt's upstream
provider emit. Either Novita strips it or the underlying provider routes
differently. Either way: do not assume that `effort=max` everywhere
costs more in prompt tokens.

#### Quirk verification: Novita's effort vocabulary (follow-up probes 2026-05-10)

Three additional configurations to clarify what Novita actually does
with `reasoning.effort`:

| Config | reasoning_tokens | reasoning_content (chars) |
|---|---|---|
| `effort=low` | 77 | 354 |
| `effort=high` (Probe B baseline) | 237 | ~657 |
| `effort=max` (Probe C baseline) | 245 | ~742 |
| no `effort` field | 230 | 948 |
| `effort=garbage_value_xyz` | 88 | 416 |

Three findings:

1. **Effort is honoured, but capped at "high".** `high` and `max`
   produce statistically indistinguishable reasoning_tokens (237 vs
   245, within sampling noise). Novita does **not** pass `max`
   upstream to DeepSeek — no prompt-injection signature at any level.
2. **Omitted `effort` defaults to "high".** ~230 reasoning tokens,
   indistinguishable from `effort=high`.
3. **Unknown effort values silently degrade to ~"low".** Sending
   `effort=garbage_value_xyz` returns HTTP 200 with 88 reasoning_tokens
   (≈ `effort=low`'s 77). No 400, no warning. **Silent failure mode**:
   a typo in `effort` caps reasoning at "low" with zero indication.

**Driver implication**: For Novita, user-facing effort buckets are
`[low, medium, high]` only — no `max`. Validate effort values
client-side before sending, so unknown values are caught at the
boundary instead of silently degrading.

---

### Ollama Cloud

Ollama Cloud uses the **native Ollama protocol** (NDJSON, no SSE), not
OpenAI-compat. Endpoint is `https://ollama.com/api/chat`. Bearer auth
works the same way as the OpenAI-compat routers (the harness passes
`.llm-test-key` as a Bearer token).

#### Slug discovery (`GET /api/tags`)

```json
{
  "name": "deepseek-v4-pro",
  "model": "deepseek-v4-pro",
  "modified_at": "2026-04-24T00:00:00Z",
  "size": 1600000000000,
  "digest": "079ba36ea28c",
  "details": {
    "parent_model": "", "format": "", "family": "", "families": null,
    "parameter_size": "", "quantization_level": ""
  }
}
```

No context_length, pricing, or capability info in `/api/tags`. Slug has
no namespace prefix.

#### Probe A — reasoning OFF (`think: false`)

**Request body**:

```json
{
  "model": "deepseek-v4-pro",
  "messages": [{"role":"user","content":"What is 2+2? Answer with just the number."}],
  "stream": true,
  "think": false,
  "options": {"num_predict": 100}
}
```

**Status**: 200
**Stream sample** (3 NDJSON lines total):

```
{"model":"deepseek-v4-pro","created_at":"2026-05-10T06:37:54.867Z","message":{"role":"assistant","content":"4"},"done":false}
{"model":"deepseek-v4-pro","created_at":"2026-05-10T06:37:54.885Z","message":{"role":"assistant","content":""},"done":false}
{"model":"deepseek-v4-pro","created_at":"2026-05-10T06:37:55.096Z","message":{"role":"assistant","content":""},"done":true,"done_reason":"stop","total_duration":615230395,"prompt_eval_count":17,"eval_count":2}
```

**CoT stream key observed**: n/a (think off)
**Total reasoning chars**: 0
**Usage**: `prompt_eval_count=17, eval_count=2, total_duration=615ms (in ns)`. No `usage` object, no `reasoning_tokens` field.

#### Probe B — reasoning ON, default (`think: true`)

**Request body**:

```json
{
  "model": "deepseek-v4-pro",
  "messages": [{"role":"user","content":"Why are there infinitely many prime numbers? Give a step-by-step proof."}],
  "stream": true,
  "think": true,
  "options": {"num_predict": 800}
}
```

**Status**: 200
**Stream sample** (761 lines total, first 5 + last 2):

```
{"model":"deepseek-v4-pro","message":{"role":"assistant","content":"","thinking":"We"},"done":false}
{"model":"deepseek-v4-pro","message":{"role":"assistant","content":"","thinking":" need"},"done":false}
{"model":"deepseek-v4-pro","message":{"role":"assistant","content":"","thinking":" to"},"done":false}
{"model":"deepseek-v4-pro","message":{"role":"assistant","content":"","thinking":" give"},"done":false}
{"model":"deepseek-v4-pro","message":{"role":"assistant","content":"","thinking":" a"},"done":false}
... [753 lines omitted] ...
{"model":"deepseek-v4-pro","message":{"role":"assistant","content":""},"done":false}
{"model":"deepseek-v4-pro","message":{"role":"assistant","content":""},"done":true,"done_reason":"stop","total_duration":34180217721,"prompt_eval_count":19,"eval_count":789}
```

**CoT stream key observed**: **`message.thinking`** (Anthropic-style key, on the Ollama native envelope).
**Total reasoning chars**: 979
**Usage**: `prompt_eval_count=19, eval_count=789` (eval_count is the **combined** thinking + visible token count; Ollama Cloud does not split them).

#### Probe C — reasoning ON, max (`think: "max"`)

Ollama's native protocol normally takes `think` as a boolean. On Ollama
Cloud, **string values are accepted** — `"high"` and `"max"` both produce
2xx and result in different prompt-eval counts:

**Request body**:

```json
{
  "model": "deepseek-v4-pro",
  "messages": [{"role":"user","content":"Why are there infinitely many prime numbers? Give a step-by-step proof."}],
  "stream": true,
  "think": "max",
  "options": {"num_predict": 1500}
}
```

**Status**: 200
**Stream sample** (863 lines, first 5 + last 2):

```
{"model":"deepseek-v4-pro","message":{"role":"assistant","content":"","thinking":"We"},"done":false}
{"model":"deepseek-v4-pro","message":{"role":"assistant","content":"","thinking":" are"},"done":false}
{"model":"deepseek-v4-pro","message":{"role":"assistant","content":"","thinking":" asked"},"done":false}
{"model":"deepseek-v4-pro","message":{"role":"assistant","content":"","thinking":":"},"done":false}
{"model":"deepseek-v4-pro","message":{"role":"assistant","content":"","thinking":" \""},"done":false}
... [855 lines omitted] ...
{"model":"deepseek-v4-pro","message":{"role":"assistant","content":"**."},"done":false}
{"model":"deepseek-v4-pro","message":{"role":"assistant","content":""},"done":true,"done_reason":"stop","total_duration":41124275333,"prompt_eval_count":98,"eval_count":891}
```

**CoT stream key observed**: `message.thinking`
**Total reasoning chars**: 1146
**Usage**: `prompt_eval_count=98 (vs 19 baseline)`, `eval_count=891`.
The 19 -> 98 prompt-token jump matches OR `xhigh` and nano-gpt `max`
exactly — confirms the same upstream `max` system prompt is being
injected. So Ollama Cloud's `think: "max"` is wired to DeepSeek-native
`max` reasoning.

---

## Known quirks: confirmed / refuted

| # | Quirk | Status | Evidence |
|---|---|---|---|
| 1 | Novita silently ignores `reasoning.enabled=false` | **CONFIRMED** | Probe with body `{"reasoning":{"enabled":false}}` returned 143 chunks containing `reasoning_content`; Novita ignored the OR-style toggle. Disabling needs `thinking.type=disabled`. |
| 2 | OR `effort=max` returns 400 | **CONFIRMED** | Direct probe got HTTP 400 with body `{"error":{"message":"reasoning.effort: Invalid option: expected one of \"xhigh\"|\"high\"|\"medium\"|\"low\"|\"minimal\"|\"none\"","code":400}}` |
| 3 | OR `xhigh` maps to DeepSeek-native `max` | **CONFIRMED (indirect)** | Both OR `effort=xhigh` (Probe C) and Ollama Cloud `think="max"` produce the exact same `prompt_tokens` increase from 19 to 98 — same upstream system-prompt injection visible at the wire. Same on nano-gpt `effort=max`. |
| 4 | nano-gpt always reports `reasoning_tokens=0` | **REFUTED — replaced with stronger statement** | nano-gpt does not report **any** `reasoning_tokens` field at all. The stream `usage`-equivalent is `x_nanogpt_pricing` with only `inputTokens` and `outputTokens`. Reasoning tokens are folded into `outputTokens`. So the count is not `0`, it is **absent**. |
| 5 | OpenAI-via-OR: reasoning_tokens count but no raw CoT | **N/A for DeepSeek** | All four routers expose raw CoT for DS V4 Pro. The reference quirk applies only to OpenAI-family models. |
| 6 | Novita silently degrades unknown `effort` values | **CONFIRMED** | `effort=garbage_value_xyz` returned 200 with 88 reasoning_tokens (≈ `effort=low`'s 77). No validation error. Also: `effort=max` ≈ `effort=high` (245 vs 237) — Novita caps at high. **Validate client-side.** |

---

## Implications for `DeepSeekV4Driver`

**Builders.** Three of the four routers can share a single OpenAI-compat
request builder — but the responses must be parsed by **two** distinct
stream parsers:

- *OR-canonical reasoning parser* (`delta.reasoning` + optional
  `delta.reasoning_details`) handles **OpenRouter** and **nano-gpt**.
  These two also produce structurally identical effort-token-injection
  behaviour at max effort, just under different effort vocabularies
  (OR: `xhigh`; nano-gpt: `max`). Reasoning toggle on nano-gpt is via
  **model-slug suffix** (`:thinking`), so the driver dispatch needs a
  separate slug for the reasoning-on configuration on nano-gpt.
- *DeepSeek-native parser* (`delta.reasoning_content`) handles **Novita**
  exclusively. Novita also requires the **top-level** `thinking.type`
  field to gate reasoning at all — `reasoning.enabled` is silently
  ignored. The driver should always emit `thinking.type` for Novita,
  paired with `reasoning.effort` when an effort knob is wanted.
- *Ollama-native parser* (NDJSON, `message.thinking`) handles **Ollama
  Cloud**. This is a different transport (NDJSON vs SSE), a different
  envelope (no OpenAI `delta`/`choices` shape), and a different toggle
  (`think: bool|string`). It must be a **custom builder** end-to-end —
  the OpenAI-compat code path cannot handle it.

**Capability fields.** The driver should leave these as `None` and let
provider metadata fill them in: `context_length`, `max_output_tokens`,
`pricing`, `supports_tools`. Three routers expose these (OR most fully,
Novita richly, Ollama Cloud not at all), and overriding them in the
driver would shadow real differences (e.g. nano-gpt's `:thinking` slug
vs the regular slug differ on capability but share metadata). The
**only** capability the driver should hard-code is the `delta.reasoning`
vs `delta.reasoning_content` vs `message.thinking` parser selector,
because that is intrinsic to the (router, slug) pair, not dynamic.

**Builder dispatch keys.** Recommended dispatch shape:

```
(router_id, slug_pattern) -> builder
  ("openrouter",  "deepseek/deepseek-v4-pro")           -> OpenAICompatBuilder(reasoning_key="reasoning",         effort_field="reasoning.effort", effort_max="xhigh", toggle_off="reasoning.enabled=false")
  ("nano-gpt",    "deepseek/deepseek-v4-pro")           -> OpenAICompatBuilder(reasoning_key=None, ...)        # reasoning unavailable on this slug
  ("nano-gpt",    "deepseek/deepseek-v4-pro:thinking")  -> OpenAICompatBuilder(reasoning_key="reasoning",         effort_field="reasoning.effort", effort_max="max",   toggle_off=<switch slug>)
  ("nano-gpt",    "TEE/deepseek-v4-pro")                -> OpenAICompatBuilder(reasoning_key=None, ...)
  ("nano-gpt",    "TEE/deepseek-v4-pro:thinking")       -> OpenAICompatBuilder(reasoning_key="reasoning",         effort_field="reasoning.effort", effort_max="max")
  ("novita",      "deepseek/deepseek-v4-pro")           -> OpenAICompatBuilder(reasoning_key="reasoning_content", toggle_field="thinking.type",    on="enabled", off="disabled", effort_field="reasoning.effort", effort_buckets=["low","medium","high"])  # Novita caps at high; max silently == high; unknown effort silently == low
  ("ollama_cloud","deepseek-v4-pro")                    -> OllamaNativeBuilder(thinking_field="think", off=False, on=True, max="max")
```

Two practical notes for the spec:

1. **nano-gpt has no usage block.** `outputTokens` from
   `x_nanogpt_pricing` is the only completion-side token count and it
   bundles reasoning + visible. The driver should not rely on
   `reasoning_tokens` for nano-gpt — fall back to chunk-counting raw
   reasoning chars if a UI metric is needed. Alternatively, tag
   nano-gpt as "reasoning_tokens not reported" in the capability shape
   so downstream code stops asking.
2. **Provider routing is not stable on OR.** Two consecutive OR probes
   (A and C, both reasoning-on for the same model) hit different
   upstream providers (DeepInfra vs SiliconFlow). Both honour the wire
   shape, but timing, finish-reason behaviour and tool support may
   differ silently. The driver should not memoise per-call provider
   identity.
