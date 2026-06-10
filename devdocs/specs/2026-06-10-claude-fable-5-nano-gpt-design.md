# Claude Fable 5 via nano-gpt — First-Class Support (Preview)

**Date:** 2026-06-10
**Status:** Approved
**Scope:** Backend only (capability YAML + two adapter touchpoints + tests)

## Goal

Offer `anthropic/claude-fable-5` (and the `anthropic/claude-fable-latest`
alias) as a first-class model on the nano-gpt route. Released as a
preview: full support, with users asked to report anomalies.

## Empirical findings (probed 2026-06-10 against nano-gpt)

All probes ran against `https://nano-gpt.com/api/v1/chat/completions`
with the project test key, mirroring the adapter's exact wire shape.

| Probe | Result |
|---|---|
| Catalogue (`/v1/models?detailed=true`) | Listed: 1M context, 128k output, `reasoning: true`, `tool_calling: true`, vision, pricing $10/$50 per M plus cache read/write fields. No `:thinking` slug variant → catalogue pipeline selects **flag-mode**. |
| `{"reasoning": {"enabled": true}}` alone | **No reasoning emitted** (0 chars, 0 reasoning tokens). Opus 4.7 reasons with the identical flag — Fable differs. |
| `enabled: true` + `effort: low/medium/high` | Reasoning streams via the `reasoning` delta field; depth and cost scale plausibly with the bucket. No INS-035-style budget explosion. |
| `enabled: false` / no reasoning field | No reasoning — toggle semantics intact. |
| `effort` together with `cache_control` markers | Reasoning still streams; no INS-036-style silent drop. |
| Unsigned thinking-block replay (hard-CoT) | Accepted, no 400. nano-gpt streams no `reasoning_details`/signature for Fable, so replayed blocks are unsigned — fine. |
| Cache metrics in usage | All zero — but identically zero for Opus 4.7 on the same probe. Known nano-gpt cache-visibility gap (2026-05-08), not a Fable regression. Cache QA stays on OpenRouter. |

**Key conclusion:** Fable 5 uses effort-based thinking control. The
`enabled` flag alone is a silent no-op; an `effort` value is required.
This conflicts with INS-037 (effort dropped for Claude-via-router),
whose rationale — runaway percentage budgets (INS-035) and the
`max_tokens`/`cache_control` collision (INS-036) — does not apply to
Fable's native effort handling, as verified above.

## Design

### 1. Capability YAML entry

`backend/modules/llm/data/model_capabilities.yaml` gains one entry:

```yaml
# Claude Fable 5 via nano-gpt — effort-based thinking, see INSIGHTS:
# unlike Sonnet/Opus, the enabled flag alone is a silent no-op; effort
# is required and verified cache-safe on this route.
- adapter: nano_gpt_http
  pattern: "anthropic/claude-fable-*"
  reasoning:
    kind: optional
    effort: { buckets: [low, medium, high], default_bucket: medium }
    default_on: true
    replay_reasoning: true
  tools: { supported: true, exclusive_with_reasoning: false }
```

- Pattern covers `claude-fable-5` and the `claude-fable-latest` alias
  (which routes to Fable 5; identical semantics).
- `default_on: true` — consistent with the rest of the Claude family.
- `default_bucket: medium` — solid reasoning depth at moderate cost,
  matching the gpt-5 entry's convention.
- `replay_reasoning: true` — hard-CoT family; unsigned replay verified.

### 2. Anthropic-detection regex

`_CLAUDE_RE` in `backend/modules/llm/_adapters/_anthropic_cache.py:28`
is extended from `claude[^/]*\b(haiku|sonnet|opus)\b` to
`claude[^/]*\b(haiku|sonnet|opus|fable)\b`.

This makes `is_anthropic_model()` return True for Fable, enabling
cache_control markers, thinking-block replay (typed `thinking` content
blocks), and StreamDone cache logging on **both** routers.

### 3. Effort-guard exception

Extending the regex alone would route Fable into the INS-037 effort
omission — turning the reasoning toggle into a silent no-op. Therefore:

- New helper `is_effort_based_claude(model_id)` in
  `_anthropic_cache.py`, matching `fable` in the slug tail (same
  tail-extraction strategy as `is_anthropic_model`).
- The effort-omission guards in `_nano_gpt_http.py` (~line 439) and
  `_openrouter_http.py` (~line 479) change from
  `not is_anthropic_model(model)` to
  `not is_anthropic_model(model) or is_effort_based_claude(model)`.
- INS-037 behaviour for Sonnet/Opus/Haiku is unchanged.

### 4. Effort plumbing verification

The implementation plan must verify that `extras.reasoning_effort` is
reliably populated with the `default_bucket` for first-class models
that declare an effort spectrum (as gpt-5 does today). If a path
exists where reasoning is on but effort is None, Fable would silently
not reason — that path must be closed (fallback to the default
bucket) or shown not to exist.

### 5. Out of scope

- **No OpenRouter YAML entry.** First-class support is nano-gpt only.
  The regex/guard changes are router-wide (correct and intended), but
  Fable on OpenRouter stays heuristic-only.
- **Almost no frontend changes.** `first_class_support` and effort
  buckets propagate through existing DTOs; the ThinkingButton effort
  pop-out is generic. One exception surfaced in final review: the
  frontend mirror of the Anthropic-detection regex
  (`frontend/src/features/llm/anthropicCache.ts`, gates the prompt-cache
  TTL dropdown in persona edit) must gain the `fable` token in
  lock-step with the Python side.
- **No preview badge or in-product messaging.** Preview communication
  happens via Discord.

### 6. INSIGHTS.md

Add an entry documenting the Fable exception to INS-037: effort is
required for reasoning, empirically cache-safe, no INS-035 budget
issue on this route.

## Tests

- `tests/modules/llm/test_capabilities.py` — resolver matches
  `anthropic/claude-fable-5` and `anthropic/claude-fable-latest` →
  `first_class_support=True`, effort spectrum present, default bucket
  `medium`.
- `tests/modules/llm/test_translation_nano_gpt.py` — for Fable:
  body carries `reasoning: {enabled: true, effort: ...}` AND
  cache_control markers coexist; reasoning off → `enabled: false`
  without effort. Regression: Sonnet/Opus still get no effort field.
- Regex/helper tests for `is_anthropic_model` (fable slugs now match)
  and `is_effort_based_claude` (fable yes; haiku/sonnet/opus no).
- Per project convention, retry/429 and adapter suites run in full
  when adapter files are touched.

## Manual verification (Chris, real instance)

1. In a nano-gpt connection, refresh the model list — *Claude Fable 5*
   appears with full metadata (1M context, vision, tools, pricing) and
   no "limited info" fallback.
2. Select Fable 5; the ThinkingButton shows the effort pop-out with
   low/medium/high, defaulting to medium.
3. Send a non-trivial prompt with thinking ON — a thinking pill streams
   before the answer.
4. Continue the conversation (multi-turn) — no 400/signature errors,
   replies stay coherent.
5. Toggle thinking OFF — next reply has no thinking pill.
6. Switch effort to low and high — visibly shorter/longer thinking.
7. Check the session token/cost display updates plausibly (Fable is
   the priciest model in the catalogue: $10/$50 per M).
