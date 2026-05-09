# LLM Reasoning & Tools Capabilities — Design

**Date:** 2026-05-09
**Status:** Draft

---

## 1. Context & Problem

Chatsune supports a growing roster of LLM providers (xAI, OpenRouter,
Novita, nano-gpt, Mistral, Ollama, Community sidecars, Anthropic via
routers). Each provider exposes reasoning and tool-use capabilities
differently, and the current model only captures a single boolean
`supports_reasoning` per model. This collapses several orthogonal
dimensions into one bit, with three painful consequences:

1. **The session UI cannot tell the user what is actually possible.**
   A model with effort buckets, a model with a boolean toggle, and a
   model with always-on reasoning all look identical to the frontend.
2. **The XOR-mutex case is invisible.** Some models cannot run tools
   and reasoning in the same request (DeepSeek R1 raw, QwQ, Magistral
   in some configurations). Today a user can enable both, the
   request goes out, and the upstream silently degrades or fails.
3. **Effort is not modelled at all.** Models with effort knobs
   (OpenAI o-series, GPT-5, Claude with token-budget translated into
   buckets, Gemini 2.5) get the same single-bit treatment as boolean
   toggles. Users who want shallower/cheaper or deeper/slower
   reasoning have no UI to express that.

Chris flagged this as the single biggest LLM UX problem in the system.
The goal of this design is a complete, honest representation of every
model's reasoning and tool capabilities, surfaced in a consistent
session-level cockpit that "users will love".

This design also retires the per-persona `reasoning_enabled` field —
reasoning belongs to the chat session, not the persona.

## 2. Goals & Non-Goals

**Goals**
- Honest per-model capability metadata covering three orthogonal axes:
  reasoning kind, tool support, tool×reasoning mutex, plus an optional
  effort spec.
- A single uniform cockpit UI per chat session: two buttons (Reasoning,
  Tools), always visible, disabled-with-tooltip when not applicable.
- A pop-out interaction for effort-capable models that includes "Off"
  as a first-class choice, so the visual state of the button is the
  same regardless of whether the model is boolean or effort-graded.
- Capability source-of-truth in a hand-curated YAML, with adapter
  heuristics as a fallback and a universal "best-effort" default for
  unknown models.
- A per-adapter translation layer that maps an internal vocabulary
  (`reasoning_mode`, `reasoning_effort`) into provider-specific
  request shapes, sending an explicit value whenever the model is
  `optional` (no reliance on provider defaults).
- Backwards-compatible storage: no MongoDB wipe, lazy reads with
  sensible defaults (per CLAUDE.md §Data-Model Migrations).

**Non-goals**
- Adding new providers. The capability model is designed to be
  extensible, but no new adapters are introduced here.
- Per-message reasoning overrides. Settings are session-scoped.
- Per-persona reasoning preference. Removed from the persona editor.
- Reasoning visibility toggle (show/hide thinking). Reasoning is
  always shown when it happens; "off" means truly off, not hidden.
  When a model is `always_on` and the only available knob is
  visibility (e.g. OpenRouter `reasoning.exclude`), we do **not**
  expose that as a user-facing switch.
- Token-budget user control. Models that internally use a budget
  (Anthropic, Gemini) are surfaced as `low/medium/high` effort
  buckets; the adapter translates buckets to budgets. Direct budget
  entry is out of scope.
- Migration scripts for legacy persona/session documents. Lazy reads
  cover everything (per CLAUDE.md and the "no Rube-Goldberg for
  legacy data" principle).

## 3. Capability Model

Three orthogonal axes, plus an optional effort spec, attached to
`ModelMetaDto`.

### 3.1 Shape

```python
# shared/dtos/llm.py

class ReasoningEffortSpec(BaseModel):
    """When non-None, the model has an effort selector."""
    buckets: list[str]              # e.g. ["low","medium","high"]
                                    # or  ["minimal","low","medium","high"]
    default_bucket: str             # selected when reasoning is first activated

class ReasoningCapability(BaseModel):
    kind: Literal["no_reasoning", "optional", "always_on"]
    effort: ReasoningEffortSpec | None = None
    default_on: bool = True         # only meaningful when kind == "optional"

class ToolCapability(BaseModel):
    supported: bool
    exclusive_with_reasoning: bool = False

class ModelMetaDto(BaseModel):
    # ... existing fields ...
    reasoning: ReasoningCapability
    tools: ToolCapability

    # Backwards-compat: keep the boolean as a computed field so
    # existing consumers (model browser filters, etc.) continue to work.
    @computed_field
    @property
    def supports_reasoning(self) -> bool:
        return self.reasoning.kind != "no_reasoning"
```

### 3.2 Worked examples

**Critical: capability is per `(adapter, model)`, not per logical
model.** The same logical model can have different capabilities
depending on the upstream that serves it. Examples below name the
adapter explicitly when it matters.

| Adapter | Model | `reasoning.kind` | `reasoning.effort` | `tools.supported` | `tools.exclusive_with_reasoning` |
|---|---|---|---|---|---|
| ollama | Llama 3.3 70B | `no_reasoning` | None | true | false |
| openrouter | qwen/qwen3-* (toggle) | `optional` | None | true | false |
| mistral | magistral-medium | `optional` | None | true | false |
| xai | grok-4-1-fast (slug-pair) | `optional` | None | true | false |
| openrouter | anthropic/claude-sonnet-4-6 | `optional` | `{low,med,high}`, def=`med` | true | false |
| openrouter | anthropic/claude-opus-4-7 | `optional` | `{low,med,high}`, def=`med` | true | false |
| openrouter | openai/o4-mini | `optional` | `{low,med,high}`, def=`med` | true | false |
| openrouter | openai/gpt-5 | `optional` | `{minimal,low,med,high}`, def=`med` | true | false |
| openrouter | google/gemini-2.5-pro | `optional` | `{low,med,high}`, def=`med` *(internal budget)* | true | false |
| **xai** | **grok-4.3** | **`optional`** *(simulated via slug-pair)* | None | true | false |
| **openrouter** | **x-ai/grok-4.3** | **`always_on`** *(no slug-pair available upstream)* | None | true | false |
| openrouter | deepseek/deepseek-r1 | `always_on` | None | **false** | n/a |
| openrouter | qwen/qwq-32b | `always_on` | None | **false** | n/a |

The bold rows make the per-upstream point concrete: Grok 4.3 via the
xAI direct adapter exposes a simulated reasoning toggle (the adapter
maps `mode=on/off` to a `reasoning_slug` / `non_reasoning_slug`
swap). Grok 4.3 via OpenRouter has no equivalent mechanism on the
router side, so the capability is honestly `always_on`. The user
gets a different cockpit depending on which upstream they routed
through — that is the truth of the situation.

**Rationale: always-on + mutex is modelled as `tools.supported=false`.**
Such models are legacy; we do not engineer special UI paths for them.
The user sees a disabled tools button with a tooltip. Adapter-internal
specifics (xAI slug pairs, nano-gpt `:thinking` suffixes, Anthropic
token budgets) stay hidden behind `kind="optional"`.

### 3.3 The `UserModelConfigDto.custom_supports_reasoning` field

Stays as-is for now. It addresses a different question ("do we trust
the adapter's capability detection?") and was added for community
sidecars. A future extension could introduce a structured override,
but that is out of scope.

## 4. Cockpit UI

### 4.1 Universal rule

**The cockpit always renders both buttons (Reasoning, Tools).** Buttons
that do not apply for the current model are shown disabled, with a
tooltip explaining why. We never hide a button (per the
disabled-over-hidden Chatsune UI principle).

### 4.2 Per-button render rules

| `reasoning.kind` | Reasoning-button state |
|---|---|
| `no_reasoning` | disabled-inactive, tooltip "model does not support reasoning" |
| `always_on` | disabled-active, tooltip "model always reasons" |
| `optional` | enabled, behaviour depends on `effort` |

| `tools.supported` | Tools-button state |
|---|---|
| `false` | disabled-inactive, tooltip "model does not support tools" |
| `true` | enabled, normal toggle |

### 4.3 Three interaction patterns for the Reasoning button

| Capability | Button behaviour |
|---|---|
| `kind=no_reasoning` | disabled; click is a no-op |
| `kind=optional, effort=None` | direct toggle (click flips on/off) |
| `kind=optional, effort≠None` | opens pop-out; selection commits immediately |
| `kind=always_on, effort=None` | disabled-active; click is a no-op |
| `kind=always_on, effort≠None` | opens pop-out; "Off" is disabled, buckets selectable |

**Pop-out content** (effort-capable models):

```
┌─────────────────────┐
│  ○ Off              │   ← button becomes "white" (inactive)
│  ○ Low              │   ← button "active", pill "L"
│  ● Medium           │   ← button "active", pill "M" (currently chosen)
│  ○ High             │   ← button "active", pill "H"
└─────────────────────┘
```

The mental model the user builds: **"Button is white = reasoning off,
button is active = reasoning on. Whether I get there by clicking
(boolean) or selecting (effort) doesn't matter — the visual state is
identical."**

### 4.4 Mutex behaviour (`tools.exclusive_with_reasoning=true`)

Only relevant when both buttons are enabled. UI rules:
- Clicking the inactive of the two automatically deactivates the other.
- Clicking the active of the two deactivates it (yielding "both off").
- Both buttons active simultaneously is not reachable through the UI.

The backend additionally validates this (§6.2) as a defence-in-depth.

### 4.5 Initial defaults on a fresh chat session

Computed from the model's capability:

| Capability shape | Defaults |
|---|---|
| `kind=optional, no mutex` | both on; effort = `default_bucket` if applicable |
| `kind=optional, mutex` | tools on, reasoning off |
| `kind=always_on, no mutex` | reasoning permanently on (effort = `default_bucket`); tools on if supported |
| `kind=always_on, mutex` | reasoning permanently on; tools button disabled (`tools.supported=false`) |
| `kind=no_reasoning` | reasoning button disabled; tools on if supported |

### 4.6 Persona editor

The current per-persona `reasoning_enabled` field is removed from the
persona editor. The DB document keeps the field for now (lazy-read
ignores it); it is not surfaced anywhere in the UI.

## 5. Capability Source-of-Truth

### 5.1 Resolution hierarchy

**Capability identity is `(adapter_type, model_id)`, not `model_id`
alone.** The same logical model can — and does — have different
capabilities depending on which upstream serves it, because:

- Some adapters can simulate a toggle that the upstream itself does
  not offer (xAI slug-pair for Grok 4.3, nano-gpt slug-pair / flag
  modes).
- Routers (OpenRouter, nano-gpt) may upstream-rebroadcast a model
  with their own quirks layered on top — fewer parameters supported,
  different field names, undocumented constraints.
- Future upstream routers may bring their own conventions that we
  have to model adapter-locally, not globally.

A single function in the LLM module combines all sources. Highest
priority first:

1. **YAML override** — `backend/modules/llm/data/model_capabilities.yaml`.
   Code-bundled (in the Docker image, no Volume), hand-curated, part
   of code review. Each entry keys on `(adapter, pattern)`.
2. **Adapter heuristic** — each adapter implements an optional
   `capability_hint(model_id) -> ModelCapabilities | None`. Used for
   adapter-specific signals: OpenRouter inspects
   `top_provider.supported_parameters`, Novita reads the `features`
   array, nano-gpt consults its `_pair_map.py`, xAI uses its slug-pair
   table.
3. **Universal fallback** — `kind="optional", effort=None,
   tools.supported=true, tools.exclusive_with_reasoning=false`. This
   mirrors today's "best-effort" behaviour.

```python
# backend/modules/llm/_capabilities.py (new)

def resolve_capabilities(
    adapter_type: str, model_id: str
) -> ModelCapabilities:
    if entry := _yaml_lookup(adapter_type, model_id):
        return entry
    if hint := _adapter_hint(adapter_type, model_id):
        return hint
    return _DEFAULT_CAPABILITIES
```

Adapters call `resolve_capabilities(...)` when assembling
`ModelMetaDto` for the model browser. The hierarchy is implemented
once, not repeated per adapter.

### 5.2 YAML format

```yaml
# backend/modules/llm/data/model_capabilities.yaml
#
# Capability overrides per (adapter_type, model_id pattern).
# Adapter heuristics are consulted only when no entry matches.

models:
  - adapter: openrouter
    pattern: "anthropic/claude-sonnet-4-6*"
    reasoning:
      kind: optional
      effort: { buckets: [low, medium, high], default_bucket: medium }
      default_on: true
    tools: { supported: true, exclusive_with_reasoning: false }

  # Grok 4.3 via xAI direct: the adapter's slug-pair lets us simulate
  # an optional toggle even though the underlying weights are always-on.
  - adapter: xai
    pattern: "grok-4.3*"
    reasoning:
      kind: optional
      default_on: true
    tools: { supported: true, exclusive_with_reasoning: false }

  # Same logical model via OpenRouter: no slug-pair available on the
  # router side, so capability is honestly always_on.
  - adapter: openrouter
    pattern: "x-ai/grok-4.3*"
    reasoning: { kind: always_on }
    tools: { supported: true, exclusive_with_reasoning: false }

  - adapter: openrouter
    pattern: "deepseek/deepseek-r1*"
    reasoning: { kind: always_on }
    tools: { supported: false, exclusive_with_reasoning: true }
```

Patterns support glob-style wildcards (`fnmatch.fnmatch` semantics).
The first matching entry wins. `(adapter, pattern)` is matched in
order; broader entries should appear after more specific ones.

### 5.3 Coverage policy

We do not need YAML coverage for every model on day one. Models
without YAML entries fall through to adapter heuristics, then to the
universal default. The user experience for those models matches
today's behaviour. YAML coverage will grow as we curate the most-used
models — Chris flagged that high-quality coverage is a quality goal,
not a launch blocker.

## 6. Translation Layer & Request Pipeline

### 6.1 Internal vocabulary

```python
class CompletionRequestExtras(BaseModel):
    tools_enabled: bool
    reasoning_mode: Literal["off", "on"]
    reasoning_effort: str | None    # one of the model's buckets, or None
```

Carried on the existing `CompletionRequest` (replaces the current
`reasoning_enabled: bool`).

### 6.2 Validation (backend, defence-in-depth)

- `tools_enabled=true` and `reasoning_mode="on"` and the model is
  mutex → 400 Bad Request, `ErrorEvent` to the client.
- `reasoning_effort` not in the model's buckets → 400.
- `reasoning_mode="on"` against a `kind="no_reasoning"` model → 400.

The UI prevents these states by construction; the backend rejects
them anyway, fail-loud.

### 6.3 Translation per provider

Each adapter implements a translation function from
`CompletionRequestExtras` to provider-specific request fields. The
"always explicit" rule applies: when the model is `optional`, the
adapter sends an explicit value for both modes, regardless of whether
the provider's default would have produced the same outcome. This
prevents drift when providers change defaults.

| Provider | `mode=on, effort=medium` | `mode=off` |
|---|---|---|
| Anthropic (direct, future) | `thinking: {type: "enabled", budget_tokens: 8192}` | `thinking` field omitted (Anthropic API has no explicit "disabled" sentinel; omission is the contract) |
| OpenAI Responses API | `reasoning: {effort: "medium"}` | omit `reasoning` for non-reasoning models; for reasoning-capable models, route via Chat Completions without `reasoning_effort` |
| OpenRouter | `reasoning: {effort: "medium"}` (or `{enabled: true}` if model has no effort spec) | `reasoning: {enabled: false}` |
| Novita | `reasoning: {effort: "medium"}` (or `{enabled: true}`) | `reasoning: {enabled: false}` |
| xAI slug-pair | switch to `reasoning_slug`, no body flag | switch to `non_reasoning_slug` |
| nano-gpt slug-mode | switch to `:thinking` slug | switch to `-nothinking` slug |
| nano-gpt flag-mode | `reasoning: {enabled: true}` | `reasoning: {enabled: false}` |
| Mistral | model variant baked in | model variant baked in |
| Ollama | model-dependent (often nothing) | model-dependent |

**Note on always-on models.** `mode=off` is unreachable for
`always_on` models because the cockpit does not allow it. Adapters
do not need to handle that combination, and we do **not** use
provider-side visibility-hide flags (e.g. OpenRouter
`reasoning: {exclude: true}`) to fake an "off" state, per §2 non-goals.

### 6.4 Bucket-to-budget translation (Anthropic, Gemini)

For providers that take a token budget rather than an effort string,
the adapter maps internal buckets to numeric budgets. Initial values
(refinable later):

| Bucket | Anthropic `budget_tokens` | Gemini `thinking_budget` |
|---|---|---|
| `low` | 2048 | 2048 |
| `medium` | 8192 | 8192 |
| `high` | 16384 | 16384 |

Bucket-to-budget is per-adapter; the user never sees the numbers.

### 6.5 Model switch within a session

When the user changes the model on an existing chat session, the
backend remaps the existing settings against the new model's
capability:

- `tools_enabled` is preserved if the new model supports tools; else `false`.
- `reasoning_mode` is preserved if the new model is `optional`;
  forced to `"on"` if `always_on`; forced to `"off"` if `no_reasoning`.
- `reasoning_effort` is preserved if the bucket exists in the new
  model's effort spec; otherwise reset to `default_bucket`; otherwise
  `None`.
- If the resulting state would violate the new model's mutex, **tools
  win** (Chris's rule: tools take precedence over reasoning when
  conflict arises).

The mapping is applied server-side and the resulting
`ChatSessionExtrasUpdatedEvent` is broadcast so all clients see the
new state.

## 7. Storage, Events, Migration

### 7.1 Storage

Session-level settings live on the chat-session document in MongoDB
(in the chat module's `chat_sessions` collection):

```python
class ChatSessionExtras(BaseModel):
    tools_enabled: bool
    reasoning_mode: Literal["off", "on"]
    reasoning_effort: str | None = None
```

Added as `extras: ChatSessionExtras | None = None` on the
`ChatSession` document model. The `None` default distinguishes
"document predates this feature, compute defaults from current
model capability and persist back" from "user explicitly chose
this state". On the first cockpit interaction (or first chat-open
after this feature ships) the backend materialises `extras` from
§4.5 defaults and writes it back to the document, so subsequent
reads find a real value.

### 7.2 Events

```python
# shared/topics.py
class Topics:
    ...
    CHAT_SESSION_EXTRAS_UPDATED = "chat.session.extras.updated"

# shared/events/chat.py
class ChatSessionExtrasUpdatedEvent(BaseEvent):
    session_id: str
    extras: ChatSessionExtras
```

User toggles a control in the cockpit → REST `PATCH
/api/chat/sessions/{id}/extras` → backend persists, validates against
the current model's capability (§6.2), broadcasts
`ChatSessionExtrasUpdatedEvent` to all sessions of the user
(multi-device sync).

### 7.3 Migration

Per CLAUDE.md §Data-Model Migrations: backwards-compatible reads,
no wipe.

| Surface | Strategy |
|---|---|
| `ModelMetaDto.supports_reasoning` | becomes `@computed_field` from `reasoning.kind != "no_reasoning"`. Existing cached `ModelMetaDto` documents (if any are persisted) deserialise via the Pydantic default for `reasoning` |
| `UserModelConfigDto.custom_supports_reasoning` | unchanged |
| Persona `reasoning_enabled` field | removed from editor UI; field stays on existing persona documents but is no longer read or written |
| `ChatSession.extras` | new field with default; existing documents read with default-empty extras, then computed from model capabilities and persisted back on first cockpit interaction |
| Per-request `reasoning_enabled: bool` on `CompletionRequest` | replaced by `extras: CompletionRequestExtras`. Internal callers (chat module, master-prompt internal calls) updated in one pass |

## 8. Tests & Manual Verification

### 8.1 Unit tests

- **Capability resolver**: YAML exact match, YAML wildcard match,
  adapter hint fallback, universal fallback. One test per layer.
- **Translation per adapter**: for each adapter, cover `mode=on`
  with each effort bucket, `mode=off`, and the always-on case.
  Assert on request body structure, not phrasing (per the
  retry-test brittleness memory).
- **Validation**: mutex violation, invalid effort bucket, mode
  against `no_reasoning` — all → 400.
- **Model-switch mapping**: 5–6 representative transitions
  (GPT-5 → Claude, Claude → DeepSeek R1, Llama → Magistral,
  Magistral → Grok 4.3, GPT-5 → Llama, Grok 4-fast → GPT-5).
  Assertions on tools/reasoning/effort post-state.

### 8.2 Frontend tests

- Cockpit rendering for each capability class (5 cases): snapshot or
  DOM tests.
- Pop-out behaviour: Off + buckets selectable, Off disabled when
  `always_on`, immediate commit.
- Mutex click logic: clicking either button deactivates the other.

### 8.3 Manual verification (real device, both desktop and mobile)

Per the Chatsune mobile breakpoint convention (`lg` only), test on
desktop and one phone.

1. **Llama 3.3** (`no_reasoning`): Reasoning button greyed with
   tooltip. Tools toggle works. Issue a web-search request → tools
   are called.
2. **Magistral** (`optional, no effort`): Reasoning toggle direct,
   no pop-out. Both switches independent.
3. **GPT-5** (`optional, effort=4-bucket`): pop-out has 5 entries
   including Off. Choose Off → button goes white. Submit a request
   with Off → no `reasoning_content` in the stream.
4. **Claude Sonnet 4.6** (`optional, effort=3-bucket`): pop-out
   has 4 entries including Off. `effort=high` is visibly longer in
   reasoning than `medium`.
5. **Grok 4.3** (`always_on`): Reasoning button disabled-active
   with tooltip. Tools work normally.
6. **DeepSeek R1** (`always_on, mutex`): Reasoning disabled-active.
   Tools button greyed with mutex tooltip.
7. **Model switch**: start on GPT-5 (Tools+Reasoning=high). Switch
   to Claude → effort stays at high. Switch to DeepSeek R1 → tools
   stay off (`tools.supported=false`), reasoning stays on
   (always-on). Switch back to GPT-5 → settings reflect the
   intermediate transitions, not the original GPT-5 state (per the
   "global per session" decision in §6.5).
8. **Persona editor**: open the persona editor for any persona; the
   reasoning toggle is gone.
9. **Multi-device sync**: open the same chat on a second client;
   change a cockpit setting on one; the other reflects the change
   within one round-trip.

### 8.4 LLM harness usage

For each provider, before merging, run a representative request
through `backend/llm_harness/` (per CLAUDE.md §LLM Test Harness)
with reasoning on / off / each effort bucket. Confirm the upstream
behaves as expected. Save scenarios under
`tests/llm_scenarios/capabilities/`.

## 9. Open Questions / Out of Scope

- **Anthropic-direct adapter.** Translation table includes Anthropic
  for completeness, but no native Anthropic adapter exists yet.
  Anthropic models are routed via OpenRouter / nano-gpt today;
  translation runs through the router's `reasoning` object. A native
  adapter is a separate future spec.
- **Effort defaults per model class.** We use `medium` as the universal
  `default_bucket`. Some models may benefit from a lower or higher
  default after empirical use; refine in YAML when needed.
- **Bucket-to-budget calibration.** §6.4 numbers are starting points.
  Refine after observing real-world cost/quality on each provider.
- **Per-model "remembered settings"**. Out of scope (§6.5 takes the
  simpler "global per session" approach). Could be revisited if tester
  feedback indicates the heavier model rotation patterns benefit
  from it.
- **INSIGHTS.md entry.** After implementation, add an INS entry
  capturing the orthogonal-axes decision and the YAML-over-heuristic
  hierarchy, so future contributors do not regress to the single-bool
  shape.
