# Kimi K2.5 / K2.6 — first-class support via KimiK2Driver

**Status:** Design — pending review
**Date:** 2026-05-12
**Scope:** Two new first-class slugs (`kimi-k2.5`, `kimi-k2.6`) on two
adapters (`ollama_http`, `novita_http`). No other adapters, no new
capability kinds, no shared-helper extraction.

Research basis: [`devdocs/research/kimi-k2-wire-shapes.md`](../research/kimi-k2-wire-shapes.md).
Driver-layer rules: [`devdocs/specs/driver-layer.md`](driver-layer.md).

## Goal

Add Kimi K2.5 and K2.6 as first-class models in Chatsune, served via
Ollama Cloud and Novita AI. The Moonshot K2 family has become a popular
choice in the community for creative work (image prompts, free-form
writing) since K2.5 dropped — exposing it as a first-class option with
correct capability surfacing is the user-facing goal.

The technical goal is to land it via the driver layer, not as an
ad-hoc per-adapter special case. The driver is responsible for the
per-(adapter, slug) capability spec, request mutations, and SSE/NDJSON
parsing. Adapters remain Kimi-agnostic.

## Non-goals

- No OpenRouter, nano-gpt, GMI, or other adapter wiring. The two
  providers Chris asked for cover the realistic use case.
- No new `ReasoningCapability` kind. Existing `optional` / `always_on` /
  `no_reasoning` are sufficient to describe what the four
  (adapter, slug) cells actually do upstream.
- No extraction of a shared `_openai_compat_novita` helper. Per
  MEMORY note `project_openai_compat_refactor`, that refactor is queued
  for a later session after a third adapter joins. Kimi reuses
  parser **structure** (mirrored, not imported) per the driver-layer
  spec rule: "logic is duplicated by design so each driver fully owns
  its chunk semantics".
- No YAML entry in `model_capabilities.yaml`. The capability dispatcher
  (`backend/modules/llm/_capabilities.py:103`) consults `match_driver`
  before falling back to YAML — a registered driver wins, same as MiMo
  and DSv4.
- No UI changes. The capability surface already drives the existing
  reasoning-toggle component; reporting `always_on` for K2.6-on-Novita
  is enough to make the toggle disappear for that cell without
  per-model UI code.

## Capability matrix (driver output)

| Slug basename | adapter_type    | reasoning.kind | default_on | tools |
|---------------|-----------------|----------------|------------|-------|
| `kimi-k2.5*`  | `ollama_http`   | `optional`     | `true`     | `true` |
| `kimi-k2.6*`  | `ollama_http`   | `optional`     | `true`     | `true` |
| `kimi-k2.5*`  | `novita_http`   | `no_reasoning` | `false`    | `true` |
| `kimi-k2.6*`  | `novita_http`   | `always_on`    | `true`     | `true` |

`first_class_support = true` on every cell. `effort = None` on every
cell — Kimi K2 has no documented effort buckets and probes did not
surface a working knob on either provider.

`default_on` is required by the `ReasoningCapability` schema but is
only meaningful on the `optional` cells; the UI ignores it when the
kind is `no_reasoning` or `always_on`. We still set semantically
honest values: `false` for `no_reasoning`, `true` for `always_on`.

`tools.supported = true` on every cell is empirically safe — the
tool-roundtrip probe succeeded for all four (adapter, slug)
combinations. This is the headline difference from MiMo-on-Novita,
which still has the chat-template bug for `xiaomimimo/*` (see
`devdocs/research/mimo-novita-tool-roundtrip-bug.md`). Kimi is not
affected.

`tools.exclusive_with_reasoning = false` everywhere — tool emission
worked with reasoning on for K2.6 on Novita (the only cell where
reasoning is on by default for tool-emit probes).

## Driver structure

Directory layout, mirroring DSv4:

```
backend/modules/llm/_drivers/kimi_k2/
  __init__.py        # KimiK2Driver class, dispatcher across adapters
  _capability.py     # kimi_k2_capability_spec(adapter_type, slug)
  _builders.py       # build_request_for_ollama_cloud / _novita
  _parsers.py        # parse_chunk_ollama_cloud / _novita
```

`KimiK2Driver` exposes the standard `Driver` protocol:

```python
class KimiK2Driver:
    PATTERNS: list[str] = ["kimi-k2.5*", "kimi-k2.6*"]

    def __init__(self) -> None:
        # Per-stream tool-call accumulator for Novita (OpenAI-fragmented).
        # Ollama emits tool_calls atomically in NDJSON and needs no
        # accumulator.
        self._novita_tool_acc = ToolCallAccumulator()

    def capability_spec(self, *, adapter_type, slug): ...
    def build_request(self, *, adapter_type, slug, request): ...
    def parse_chunk(self, *, adapter_type, slug, chunk): ...
```

For each method, unsupported `adapter_type` values raise
`NotImplementedError` with a single canonical message (helper
`_unsupported_adapter`, same pattern as `MiMoV25Driver`).

### Slug-to-version dispatch

K2.5 vs K2.6 differ on Novita (`no_reasoning` vs `always_on`). The
dispatch is by `slug.startswith("kimi-k2.6")` / `startswith("kimi-k2.5")`
on the basename — defensive, no fnmatch needed inside the driver since
the registry has already done the PATTERNS match. A small helper
`_kimi_version(slug)` returning `"k2.5"` or `"k2.6"` localises the
choice.

For Novita, the slug arrives prefixed (`moonshotai/kimi-k2.6`), so the
helper strips the slash prefix the same way `match_driver` does.

### `_capability.py`

```python
def kimi_k2_capability_spec(*, adapter_type: str, slug: str) -> ResolvedCapabilities:
    if adapter_type == "ollama_http":
        return ResolvedCapabilities(
            reasoning=ReasoningCapability(kind="optional", effort=None, default_on=True),
            tools=ToolCapability(supported=True, exclusive_with_reasoning=False),
            first_class_support=True,
        )
    if adapter_type == "novita_http":
        version = _kimi_version(slug)
        if version == "k2.5":
            return ResolvedCapabilities(
                reasoning=ReasoningCapability(kind="no_reasoning", effort=None, default_on=False),
                tools=ToolCapability(supported=True, exclusive_with_reasoning=False),
                first_class_support=True,
            )
        # k2.6
        return ResolvedCapabilities(
            reasoning=ReasoningCapability(kind="always_on", effort=None, default_on=True),
            tools=ToolCapability(supported=True, exclusive_with_reasoning=False),
            first_class_support=True,
        )
    raise _unsupported_adapter(adapter_type)
```

### `_builders.py`

**Ollama Cloud (both versions)**:

Delegate to `_ollama_http.build_request_body(request)`, then set the
`think` field explicitly per `reasoning_mode`:

- `reasoning_mode == "off"` → `body["think"] = False`
- otherwise → `body["think"] = True`

Probe-confirmed: `think: true/false` is honoured for both K2.5 and K2.6
on Ollama Cloud, with `message.thinking` populated when on and empty
string when off.

**Novita (both versions)**:

Delegate to `_novita_http.build_request_body(request)`. The base body
will include a `reasoning` block whenever the model is reasoning-capable
by spec, but on Novita Kimi the field is not honoured for either
version — drop it cleanly:

- K2.5: drop `reasoning` (probe shows it's a no-op anyway, but cleaner
  wire and matches the `no_reasoning` capability).
- K2.6: drop `reasoning` (probe confirmed `reasoning: {enabled: false}`
  does NOT suppress reasoning; setting `reasoning: {enabled: true}` is
  no-op vs. omitting the field).

Both are simple `base.pop("reasoning", None)` calls — no
`enable_thinking` hack like MiMo needs.

### `_parsers.py`

**`parse_chunk_ollama_cloud(chunk)`** (stateless, no accumulator):

- `message.content` → `ContentDelta`
- `message.thinking` → `ThinkingDelta`
- `message.tool_calls[]` → list of `ToolCallEvent` (atomic, full
  arguments dict per call; `arguments` is an object on Ollama, must be
  JSON-stringified before emit to match `ToolCallEvent.arguments: str`)
- `done == True` → `StreamDone(input_tokens=prompt_eval_count, output_tokens=eval_count, reasoning_tokens=None)`
- `done_reason in {"content_filter", "refusal"}` → `StreamRefused`

Ollama does not report reasoning_tokens separately. `reasoning_tokens`
is set to `None` on `StreamDone` — this matches existing DSv4-Ollama
behaviour.

**`parse_chunk_novita(chunk, tool_acc)`** (stateful tool accumulator):

Same shape as `parse_chunk_novita` for DSv4 — implementation mirrored,
not imported:

- `delta.content` → `ContentDelta`
- `delta.reasoning_content` → `ThinkingDelta`
- `delta.tool_calls[]` (fragmented) → feed into `tool_acc`
- `finish_reason == "tool_calls"` → emit `ToolCallEvent`s from
  `tool_acc.finalised()`
- `finish_reason in _REFUSAL_REASONS` → `StreamRefused`
- terminal `usage` block → `StreamDone(input_tokens, output_tokens, reasoning_tokens)` where reasoning_tokens is read from `completion_tokens_details.reasoning_tokens` (probe confirmed Novita populates this for K2.6).

`StreamRefused` and `StreamDone` remain mutually exclusive terminal
states.

## Registry wiring

`backend/modules/llm/_drivers/__init__.py`:

```python
DRIVER_REGISTRY: list[type[Driver]] = [
    DeepSeekV4Driver,
    MiMoV25Driver,
    KimiK2Driver,           # new
]
```

PATTERNS check:

- `DeepSeekV4Driver.PATTERNS` = `["deepseek-v4-pro*", "deepseek-v4-flash*"]`
- `MiMoV25Driver.PATTERNS` = `["mimo-v2.5-pro*"]`
- `KimiK2Driver.PATTERNS` = `["kimi-k2.5*", "kimi-k2.6*"]`

No overlap — first-match-wins never has to break a tie.

## Tests

New file: `backend/modules/llm/tests/test_kimi_k2_driver.py`, modelled
on `test_mimo_v25_driver.py`.

Coverage:

1. **PATTERNS matching** — `match_driver("kimi-k2.5")`,
   `match_driver("kimi-k2.6")`,
   `match_driver("moonshotai/kimi-k2.5")`,
   `match_driver("moonshotai/kimi-k2.6")` all return `KimiK2Driver`.
   `match_driver("kimi-k2.4")` returns `None` (negative test).
2. **Capability spec** — one parametrised test per cell in the matrix
   (4 cases × adapter_type, slug). Asserts on `reasoning.kind`,
   `reasoning.default_on`, `tools.supported`,
   `tools.exclusive_with_reasoning`, `first_class_support`.
3. **Unsupported adapter** — `capability_spec`, `build_request`, and
   `parse_chunk` each raise `NotImplementedError` for
   `adapter_type="openrouter_http"`, `"nano_gpt_http"`,
   `"gmi_http"`.
4. **Builders, Ollama** — `reasoning_mode="on"` writes `think: True`;
   `reasoning_mode="off"` writes `think: False`. Tools array is
   passed through unmodified.
5. **Builders, Novita K2.5** — `reasoning` block is absent from the
   final body regardless of `reasoning_mode` (it's a no-op model
   on this provider).
6. **Builders, Novita K2.6** — `reasoning` block is absent from the
   final body regardless of `reasoning_mode` (provider ignores the
   toggle).
7. **Parsers, Novita** — fixture chunks for: content-only delta,
   reasoning_content delta, OpenAI-fragmented tool_call across three
   chunks then `finish_reason: tool_calls`, terminal usage block,
   refusal via `finish_reason: content_filter`. Each asserts on the
   exact `ProviderStreamEvent` list produced.
8. **Parsers, Ollama** — fixture chunks for: content, thinking,
   atomic tool_calls in `message.tool_calls`, terminal `done: true`
   with prompt_eval_count/eval_count, refusal via
   `done_reason: content_filter`.

Existing test updates:

- `test_driver_registry.py` — add `test_registry_contains_kimi`
  mirroring the existing `test_registry_contains_dsv4` pattern.
  The file does not enforce ordering, only presence.
- `test_capabilities_with_drivers.py` — review for exhaustive
  driver-fed slug enumeration; add Kimi cases only if the file
  iterates such a list (no churn-only edits otherwise).

No `model_capabilities.yaml` edits — capability dispatcher consults the
driver before YAML, same as DSv4 / MiMo.

## Manual verification

Run after implementation, on a real Chatsune instance with a Kimi-capable
connection set up for each provider:

- Create a connection for **Ollama Cloud** in the Chatsune UI; verify the
  models list includes `kimi-k2.5` and `kimi-k2.6` as selectable models.
- Create a connection for **Novita AI** with a `moonshotai/*` slug
  template; verify both Kimi versions appear.
- For each of the 4 (adapter, slug) cells:
  - Open a chat with the model.
  - Confirm the reasoning toggle appears only when capability is
    `optional` (Ollama K2.5, Ollama K2.6) and is hidden on Novita.
  - Send a short prompt and verify visible content is rendered.
  - On the optional cells, toggle reasoning OFF and confirm no
    thinking is rendered; toggle ON and confirm thinking appears in
    the UI's reasoning channel.
  - On Novita K2.6, confirm reasoning is rendered by default (since
    upstream always emits it) without needing a toggle.
- For tool use:
  - Enable a tool (e.g. websearch) and ask the model a question that
    requires the tool. Verify it emits a tool call.
  - Verify the second turn (after tool result) succeeds and produces a
    final answer. This is the key acceptance criterion — MiMo fails
    this on Novita; Kimi must pass.

## Risk register

- **K2.6 reasoning toggle hidden on Novita** — users coming from
  K2.5-on-Novita (where no toggle exists for a different reason:
  `no_reasoning`) may be confused that K2.6's "always emits a long
  thinking block". This is upstream behaviour; documented in the
  driver-layer docstring and in this design. Not a blocker.
- **Tool ID format differs across cells** (probe finding:
  `functions.get_weather:0` vs `functions_get_weather_0`). The driver
  echoes IDs verbatim, so no normalisation is needed. Cross-cell
  conversation history won't migrate between Ollama and Novita anyway
  (different connections).
- **Novita upstream chat-template regression** — if Novita ever pushes
  a regression that breaks Kimi tool roundtrip the way it broke MiMo,
  the driver's `tools.supported = true` would become a lie. Mitigation:
  the research note carries the same quarterly re-probe convention as
  MiMo. Re-probe target: 2026-08-12.

## Migration / rollback

Zero schema impact — no DB models change. The driver registry change is
append-only; reverting to remove Kimi requires only removing the entry
from `DRIVER_REGISTRY` and the new files. No backwards-compat
considerations.

## Open questions

None at design time. All four cells empirically verified
(`devdocs/research/kimi-k2-wire-shapes.md`).
