# Driver Layer Spec — Per-Family Premium Adapters

**Status**: Draft
**Date**: 2026-05-10
**Authors**: Chris, Claude
**Companion research**: [`devdocs/research/deepseek-v4-wire-shapes.md`](../research/deepseek-v4-wire-shapes.md)

---

## Context

Chatsune's LLM module today routes inference through generic per-router
adapters (`backend/modules/llm/_adapters/_openrouter_http.py`,
`_nano_gpt_http.py`, `_novita_http.py`, `_ollama_http.py`, …) plus a
declarative capability table (`backend/modules/llm/data/model_capabilities.yaml`).
This works well for the long tail: a model that is "just another
OpenAI-compat call" needs no per-model code.

It does **not** work for premium models — the ones our users actually
use day to day. The DeepSeek V4 wire-shape research showed that the
"same" model behaves differently across four routers in fairly bizarre
ways:

- nano-gpt encodes reasoning as a separate **slug** (`:thinking` suffix),
  not as a runtime toggle.
- Novita silently degrades unknown `effort` values to "low" with HTTP
  200 — no validation error.
- The CoT stream key differs across all four routers
  (`delta.reasoning` / `delta.reasoning_content` / `message.thinking`).
- nano-gpt has no `usage` block at all on stream completion; only its
  proprietary `x_nanogpt_pricing`.
- Effort vocabularies and caps are not portable: OR's `xhigh` ≡
  nano-gpt's `max` ≡ Ollama's `think="max"` ≡ DeepSeek-native max.
  Novita's `max` ≡ Novita's `high` (silently).

A declarative table cannot encode this. The Driver Layer does.

---

## Goals

1. **First-class support** for premium models' router-specific quirks —
   one driver per *model family* (not per model id), shared across all
   routers that expose that family.
2. **Coexist** with the existing `model_capabilities.yaml` path. The
   yaml stays the source of truth for non-premium models (Claude / GPT-5
   already work well there).
3. **Driver as the realism boundary**: when a router's documentation
   diverges from observed behaviour, the driver embodies the observed
   behaviour and validates user input *before* it hits the wire (so
   silent degradations become loud errors).
4. **User-level escape hatch**: a `force_default_routing` toggle on the
   per-model configuration, so users can opt out of a driver if it
   misbehaves and fall back to the generic adapter path.
5. **Differentiation**: this is the "BMW unter den chat-harnesses" lever
   — by handling what providers *actually* do (not what they *claim*)
   we offer something competitors don't.

## Non-Goals

- **Not** replacing adapters. Adapters keep transport, auth, retry,
  rate-limit handling, SSE/NDJSON envelope decoding.
- **Not** replacing `model_capabilities.yaml`. It stays in production
  for non-premium models indefinitely.
- **Not** auto-discovery of capabilities — that is a separate spec.
- **Not** opening the door to >20 drivers. Quality bar over breadth:
  ~15-20 driver families total, reactively grown based on user demand
  and observed router weirdness.

---

## Architecture overview

```
┌─────────────────────────────────────────────────────────────┐
│ Inference flow                                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   UserRequest ─▶ ConnectionResolver ─▶ adapter_type, slug   │
│                                          │                  │
│                                          ▼                  │
│                                  DriverRegistry.match(slug) │
│                                  ├── matched? use Driver    │
│                                  └── no match: legacy path  │
│                                                             │
│   Driver flow:                                              │
│     capability_spec(adapter_type, slug)  ───▶ ModelCaps     │
│         (driver-explicit + provider-metadata merge)         │
│     build_request(adapter_type, slug, ...) ─▶ RequestSpec   │
│     ─── handed to Adapter for transport ───▶ raw chunks ──┐ │
│     parse_chunk(adapter_type, slug, chunk) ◀──────────────┘ │
│                              │                              │
│                              ▼                              │
│                          inference events                   │
└─────────────────────────────────────────────────────────────┘
```

Two-level dispatch:

1. **Driver-level**: basename of `slug` (i.e. `slug.rsplit("/", 1)[-1]`)
   matched fnmatch-style against each driver's `PATTERNS`. First match
   wins. Drivers are siblings, not hierarchical.
2. **Builder/Parser-level** (inside a driver): `(adapter_type,
   slug-suffix)` lookup with a default fallback. nano-gpt's `:thinking`
   suffix is the canonical example.

---

## Driver protocol

```python
# backend/modules/llm/_drivers/_protocol.py

class Driver(Protocol):
    PATTERNS: ClassVar[list[str]]
    """fnmatch patterns matched against the slug basename. Multiple
    patterns are supported — drivers commonly need to match different
    naming conventions across routers (e.g. claude-haiku-4.5* vs
    claude-haiku-4-5*)."""

    def capability_spec(
        self,
        *,
        adapter_type: str,
        slug: str,
        provider_metadata: ProviderMetadata | None,
    ) -> ModelCapabilities:
        """Return the merged capability spec for this (adapter, slug).
        Fields the driver leaves as None are filled from
        provider_metadata. Driver-explicit fields win."""

    def build_request(
        self,
        *,
        adapter_type: str,
        slug: str,
        request: InferenceRequest,
    ) -> RequestSpec:
        """Construct the wire-level request body. Returns a
        RequestSpec containing endpoint path (so Ollama-style
        '/api/chat' vs OpenAI-style '/v1/chat/completions' is
        explicit), body, and any header overrides."""

    def parse_chunk(
        self,
        *,
        adapter_type: str,
        slug: str,
        chunk: dict[str, Any],
    ) -> list[InferenceEvent]:
        """Translate a single decoded chunk (post-SSE-decoding or
        post-NDJSON-line) into zero or more InferenceEvents. Reasoning
        content extraction lives here — the driver knows whether to
        read delta.reasoning, delta.reasoning_content, or
        message.thinking."""
```

File layout per driver:

```
backend/modules/llm/_drivers/
  __init__.py             # DRIVER_REGISTRY = [DeepSeekV4Driver, ...]
  _protocol.py            # Driver Protocol, RequestSpec, helpers
  _registry.py            # match_driver(slug) -> Driver | None
  deepseek_v4/
    __init__.py           # exposes DeepSeekV4Driver
    _capability.py        # capability spec construction
    _builders.py          # _BUILDERS dict + Builder classes
    _parsers.py           # _PARSERS dict + Parser classes
```

One package per family. A package may grow to multiple files; a
trivial driver may collapse to one file. The hard rule is: **one
driver = one model family**, not one model id.

---

## Registry & dispatch

```python
# backend/modules/llm/_drivers/_registry.py

DRIVER_REGISTRY: list[type[Driver]] = [
    DeepSeekV4Driver,
    # GemmaFamilyDriver, ...
]

def match_driver(slug: str) -> type[Driver] | None:
    basename = slug.rsplit("/", 1)[-1]
    for driver_cls in DRIVER_REGISTRY:
        for pattern in driver_cls.PATTERNS:
            if fnmatch.fnmatch(basename, pattern):
                return driver_cls
    return None
```

**Force-default-routing**: every per-connection-model config gains a
new optional field `force_default_routing: bool = False`. The
inference dispatcher checks this *before* `match_driver` and skips the
driver path entirely when set. UI surfaces this as an opt-in toggle
with a warning ("you will lose advanced capabilities for this
model"). Default off for first-class models.

**Fallback path**: when no driver matches *or* the user has forced
default routing, the existing flow runs unchanged: adapter handles
transport, `model_capabilities.yaml` handles capability resolution,
no driver involvement.

---

## Builders & parsers

Inside a driver, `(adapter_type, slug-suffix)` resolves to a Builder
and a Parser. The default-handler-with-overrides pattern:

```python
# backend/modules/llm/_drivers/deepseek_v4/_builders.py

class DeepSeekV4Driver:
    PATTERNS = ["deepseek-v4-pro*", "deepseek-v4-flash*"]

    _BUILDERS: dict[str, Builder] = {
        "novita": NovitaBuilder(),     # quirk: thinking.type top-level
        "ollama_http": OllamaBuilder(),  # native Ollama protocol
    }
    _DEFAULT_BUILDER = OpenAICompatBuilder()  # OR + nano-gpt

    _PARSERS: dict[str, Parser] = {
        "novita": NovitaParser(),       # delta.reasoning_content
        "ollama_http": OllamaParser(),   # message.thinking, NDJSON
    }
    _DEFAULT_PARSER = OpenRouterCanonicalParser()  # delta.reasoning

    def builder_for(self, adapter_type: str) -> Builder:
        return self._BUILDERS.get(adapter_type, self._DEFAULT_BUILDER)

    def parser_for(self, adapter_type: str) -> Parser:
        return self._PARSERS.get(adapter_type, self._DEFAULT_PARSER)
```

Adding a new OpenAI-compat router (e.g. GMI Cloud) requires no driver
change — it inherits the default builder/parser. Routers with
genuine quirks register an override entry and stay isolated to their
own Builder/Parser class.

**Slug-suffix routing** (nano-gpt's `:thinking`) is handled inside
the OpenAI-compat builder by inspecting `request.slug`. The driver
PATTERNS match both with and without suffix; the builder switches
behaviour based on the suffix.

---

## Effort bucket translation

User-facing effort scale is **per-driver**, defined by the model
family's official docs — not a single global scale shared across all
drivers. For DeepSeek V4, the model author defines exactly two effort
levels:

```
high | max
```

per [DeepSeek's thinking-mode docs](https://api-docs.deepseek.com/guides/thinking_mode)
(quote: "low and medium are mapped to high"). We expose those two and
only those two. Routers that accept additional vocabulary (OR's
`minimal`/`low`/`medium`, Novita's silent-low for unknown values) are
**not** exposed — their behaviour is not specified by DeepSeek and
varies router-to-router. This is the empirical-truth principle applied
at the model-author layer: the model author's docs trump router
extensions.

Per-router translation table for `DeepSeekV4Driver`:

| Router | user `high` | user `max` | Notes |
|---|---|---|---|
| OR | `reasoning.effort=high` | `reasoning.effort=xhigh` | xhigh injects DS-native max system prompt (prompt_tokens 19→98) |
| nano-gpt `:thinking` | `reasoning.effort=high` | `reasoning.effort=max` | both honoured upstream |
| Novita | `reasoning.effort=high` | **rejected client-side** | Novita silently caps at high (probed evidence); we refuse rather than degrade |
| Ollama Cloud | `think=true` | `think="max"` | Ollama only distinguishes default vs max |

The driver is the single source of truth for what user-effort maps to
per (adapter_type, slug), and **whether the user-effort is even valid
for that combination**. Invalid combinations raise at request-build
time with a clear error — no silent degradation.

---

## Capability spec & provider-metadata merge

Driver returns a `ModelCapabilities` shaped to match `shared/dtos/llm.py`.
Fields fall into three buckets:

| Field | Source | Rationale |
|---|---|---|
| `reasoning.kind` | Driver-explicit | structural; doesn't vary by router |
| `reasoning.effort.buckets` | Driver-explicit | router-specific, derived from translation table |
| `reasoning.exclusive_with_tools` | Driver-explicit | model-intrinsic |
| `tools.supported` | Driver-explicit | model-intrinsic |
| `supports_vision` | Driver-explicit | model-intrinsic |
| `context_length` | **None** → provider | varies per slug-variant (e.g. nano-gpt TEE = 800k) |
| `max_output_tokens` | **None** → provider | varies per router |
| `pricing` | **None** → provider | provider authoritative |
| `recommended_context_window` | (deferred per INS-039) | not in scope yet |

Merge order on read: **driver explicit > provider metadata > field
default**. Driver explicit means a non-`None` value the driver
returned. Provider metadata is fetched from the connection's adapter
(each adapter exposes a method to fetch its `/models` payload, with
caching at the adapter level — out of scope here).

For nano-gpt specifically: provider-metadata-fetch must pass
`?detailed=true` to the `/v1/models` endpoint. Without it the response
is sparse and most fields fall through to defaults.

---

## Worked example: `DeepSeekV4Driver`

**Family**: DeepSeek V4 Pro and DeepSeek V4 Flash (identical wire
format; differ only in size and pricing).

**File**: `backend/modules/llm/_drivers/deepseek_v4/`.

**Patterns**:

```python
PATTERNS = ["deepseek-v4-pro*", "deepseek-v4-flash*"]
```

These match (after basename stripping):
- OR: `deepseek/deepseek-v4-pro` → `deepseek-v4-pro`, matches ✓
- nano-gpt: `deepseek/deepseek-v4-pro:thinking` → `deepseek-v4-pro:thinking`, matches ✓
- nano-gpt TEE: `TEE/deepseek-v4-pro` → `deepseek-v4-pro`, matches ✓
- Novita: `deepseek/deepseek-v4-pro` → `deepseek-v4-pro`, matches ✓
- Ollama Cloud: `deepseek-v4-pro` → `deepseek-v4-pro`, matches ✓

**Builder dispatch table** (mirrors the research doc, condensed):

| (adapter_type, slug-suffix) | Builder | Toggle | Effort field | Effort scale (router-side) |
|---|---|---|---|---|
| `(openrouter, *)` | `OpenAICompatBuilder` | `reasoning.enabled` | `reasoning.effort` | low/medium/high/xhigh |
| `(nano_gpt, no :thinking)` | `OpenAICompatBuilder` (reasoning disabled) | n/a | n/a | n/a |
| `(nano_gpt, :thinking)` | `OpenAICompatBuilder` | slug-suffix | `reasoning.effort` | high/max |
| `(novita, *)` | `NovitaBuilder` | top-level `thinking.type` | `reasoning.effort` | low/medium/high |
| `(ollama_http, *)` | `OllamaBuilder` | top-level `think` (bool/string) | n/a | true / "max" |

**Parser dispatch**:

| adapter_type | Parser | Stream key | Transport |
|---|---|---|---|
| `openrouter` | `OpenRouterCanonicalParser` | `delta.reasoning` (+ `reasoning_details[]`) | SSE |
| `nano_gpt` | `OpenRouterCanonicalParser` | `delta.reasoning` | SSE |
| `novita` | `NovitaDeepSeekNativeParser` | `delta.reasoning_content` | SSE |
| `ollama_http` | `OllamaNativeParser` | `message.thinking` | NDJSON |

**Capability spec** (driver-explicit fields):

```python
ModelCapabilities(
    reasoning=ReasoningCapability(
        kind="optional",
        effort=ReasoningEffortSpec(
            buckets=["high", "max"],   # DeepSeek-native vocabulary
            default_bucket="high",
        ),
        default_on=True,
    ),
    tools=ToolCapability(supported=True, exclusive_with_reasoning=False),
    supports_vision=False,
    # context_length, max_output_tokens, pricing left None — provider fills
)
```

For the `(novita, *)` capability spec, the driver returns
`effort.buckets=["high"]` (max removed) so the UI never offers "max"
as an option on Novita. If "max" somehow reaches the Novita builder
anyway (e.g. an out-of-band caller), the builder rejects it with a
clear error rather than silently degrading to high.

---

## Coexistence with `model_capabilities.yaml`

The driver layer does not replace the yaml; both run.

**Lookup order on capability resolution**:

1. `match_driver(slug)` — if a driver matches, use its `capability_spec`
2. otherwise fall through to existing yaml fnmatch resolution
3. otherwise fall through to adapter heuristic defaults (already in code)

Drivers always win when both match. Existing yaml entries for Claude
4.5/4.6/4.7 and GPT-5 stay in place — they are battle-tested and
there is no need to migrate them until/unless we want to encode
quirks the yaml cannot express.

**When to add a driver vs a yaml entry**:

- Add a yaml entry when: model is well-behaved, generic OpenAI-compat,
  no per-router quirks worth encoding, no special wire shape.
- Add a driver when: model has router-specific quirks, multiple stream
  key variants, slug-based mode switching, validation rules that
  differ from "what fnmatch can express", or the model is high-volume
  enough that polish matters.

Migration path: a model that starts in yaml can graduate to a driver
when its quirks accumulate. The reverse should never be needed.

---

## Manual verification

Once `DeepSeekV4Driver` ships, verify on a real account:

1. **Driver dispatch is taken**:
   - Configure a Connection for OpenRouter, add `deepseek/deepseek-v4-pro`.
   - Inspect logs: should see `driver=deepseek_v4 builder=openai_compat` lines.
2. **Effort translation**:
   - Send a reasoning prompt with effort=`max` from the UI. Backend log
     should show `reasoning.effort=xhigh` on the wire.
   - Repeat against Novita (same model id). Backend log should show
     `thinking.type=enabled, reasoning.effort=high` (with a warning if
     user picked `max` — UI should not even let them).
3. **CoT extraction**:
   - Reasoning prompt against Novita: backend should emit reasoning
     events extracted from `delta.reasoning_content`.
   - Reasoning prompt against Ollama Cloud: backend should emit
     reasoning events extracted from `message.thinking` (NDJSON).
4. **Provider-metadata-merge**:
   - Connect to nano-gpt and select `TEE/deepseek-v4-pro`. Capability
     spec surfaced to the UI should show `context_length=800000`
     (from `?detailed=true` provider metadata), not 1M (from the
     regular slug).
5. **Force-default-routing toggle**:
   - Enable `force_default_routing` on a DS V4 Pro connection.
   - Send the same reasoning prompt. Backend log should show driver
     dispatch was *skipped*, generic adapter path used. Reasoning may
     or may not appear depending on the generic adapter — the toggle
     is a deliberate downgrade.
   - Disable the toggle. Reasoning should be back to driver-routed.
6. **Coexistence**:
   - On the same account, use Claude (`anthropic/claude-sonnet-4.7`) —
     should still resolve via yaml, no driver change. Verify log line.

---

## Out of scope

- **Other concrete drivers** (Gemma 4 family, Mistral family, Claude
  family, GPT-5 family) — each gets its own spec when implemented.
- **Driver-specific FastAPI sub-routers** — covered by the existing
  adapter sub-router pattern; drivers do not add new HTTP surface.
- **Capability auto-discovery** — separate spec, future. Today's
  provider-metadata-merge is manual: the adapter's models endpoint
  is fetched and parsed, no inference of unknown fields.
- **Effort scale changes** — the `low/medium/high/max` user-facing
  scale is fixed for this spec. Future drivers may extend it; that is
  a follow-up decision.
- **`recommended_context_window`** — deferred per
  [INS-039](../INSIGHTS.md). Not yet a capability field.
