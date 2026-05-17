# Reasoning + Tool Re-Injection Across Turns — Design Specification

**Date:** 2026-05-17
**Status:** Approved (pre-implementation)
**Source brief:** [PRE-BRANCHING.md §(b)](../../PRE-BRANCHING.md) findings b-1, b-2, b-3, b-4 (already shipped), b-5
**Scope:** Make every assistant turn faithful to the model when replayed in subsequent turns — thinking blocks (with provider signature where applicable) and tool-call / tool-result triplets must round-trip cleanly. Prerequisite for branching, also corrects degradations in linear multi-turn chats today.

---

## 1. Problem statement

Today the orchestrator's history loop
(`backend/modules/chat/_orchestrator.py:852-879`) reads only `doc["content"]`
and a couple of attachment-related fields when assembling the message list
for the next inference. `doc["thinking"]`, `doc["events"]`, and the legacy
`doc["tool_calls"]` are dropped on the floor. Consequences:

- **Hard-CoT models** (Anthropic Claude, xAI Grok reasoning, Mistral Magistral, OpenAI o-series) lose their own reasoning trace between turns. Anthropic actively rejects tool-use conversations that omit prior thinking blocks with their signature.
- **Tool-using models** of every flavour see past tool-augmented turns as plain assistant text. The model has no record it ever called `web_search` / `write_journal_entry` / etc., what arguments it used, or what came back.
- **Branching multiplies the damage.** A branch off a tool-using turn becomes a strictly weaker conversation than the original.

This spec fixes all three for both linear and branched conversations.

---

## 2. Out of scope

- Tool-result *truncation* (PRE-BRANCHING Q9). Deferred to 0.3.0 pending user feedback.
- Anthropic native adapter. We continue to reach Claude via OpenRouter / nano-gpt OpenAI-compat shape.
- Soft-CoT replay (DeepSeek-R1 / Kimi / MiMo / GLM-5). Capability flag explicitly *forbids* replay for these families — see §6.

---

## 3. Data model

### 3.1 Structured thinking blocks on `CompletionMessage`

`shared/dtos/inference.py` — add a new optional field to `CompletionMessage`:

```python
class ThinkingBlock(BaseModel):
    """One reasoning segment from an assistant turn.

    Hard-CoT providers (Anthropic, xAI Grok, Mistral Magistral) emit
    discrete thinking blocks alongside the visible content stream.
    Soft-CoT providers (DeepSeek-R1 family, Kimi, MiMo, GLM-5) emit
    a single inline ``<think>`` block parsed out post-hoc by
    ``_soft_cot_parser``; for those families we still capture the text
    here but the ``replay_reasoning`` capability flag (see §6) is
    ``False`` so the block is never sent back to the model.
    """

    text: str
    # Anthropic-specific opaque server token; replay verbatim if present.
    # Provider-rejects on tampering. None for non-Anthropic routes.
    signature: str | None = None
    # Adapter-supplied raw block dict for round-tripping unknown fields
    # (Anthropic's ``reasoning_details`` may carry extra metadata we
    # don't want to model individually). Optional; advisory only.
    raw: dict | None = None


class CompletionMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: list[ContentPart]
    tool_calls: list[ToolCallResult] | None = None
    tool_call_id: str | None = None
    # NEW. Assistant-role only. Hard-CoT reasoning blocks to replay.
    # Adapter translates to provider-native wire format.
    thinking_blocks: list[ThinkingBlock] | None = None
```

The field is **additive and optional**. Adapters that don't push thinking back simply ignore it.

### 3.2 Persistence schema on `ChatMessageDocument`

`backend/modules/chat/_repository.py` already stores `thinking` (a flat
string) and `events` (a chronological timeline). We add a new field
**alongside** (not replacing) the existing ones for backwards compatibility:

```python
# New optional field; absent on legacy documents and read with default [].
"thinking_blocks": list[dict]   # [{text, signature, raw}, ...]
```

**Backwards compatibility (CLAUDE.md hard rule).** Existing assistant
documents have `thinking: str` and no `thinking_blocks`. The history loop
handles both:

1. If `doc["thinking_blocks"]` is present, use it verbatim (new path).
2. Else if `doc["thinking"]` is a non-empty string, wrap it as
   `[ThinkingBlock(text=doc["thinking"], signature=None)]` (legacy path,
   no signature → Anthropic rejects → strip-and-retry, see §7).
3. Else, no thinking on this turn.

No migration script required. The `thinking` field stays as a
human-readable fallback and continues to be written by `save_message`.

### 3.3 Tool calls — read from existing `events` timeline

We **do not** introduce a new column. The chronological `events` field
on each assistant document already carries the data we need
(`backend/modules/chat/_inference.py:114, 763, 778`):

```python
# Existing event shape produced by the inference loop:
{"kind": "tool_call",   "id": "...", "name": "...", "arguments": "..."}
{"kind": "tool_result", "id": "...", "name": "...", "result_content": "..."}
```

The history-expansion code (§4.2) walks these and produces the
`assistant(tool_calls=…)` + one `role="tool"` per result message
triplet that adapters already know how to translate.

---

## 4. Orchestrator history expansion

### 4.1 Where

`backend/modules/chat/_orchestrator.py:852-879` — the existing
`for doc in selected_history` loop. Today it produces exactly one
`CompletionMessage` per document. We replace that with an expansion
function.

### 4.2 Expansion algorithm

```python
def _expand_history_doc(
    doc: dict,
    *,
    replay_reasoning: bool,
    replay_tool_history: bool,
) -> list[CompletionMessage]:
    """Expand one stored message document into 1..N CompletionMessages.

    User messages: always one message (unchanged from today).
    Assistant messages: zero or one assistant message (possibly with
    tool_calls), plus zero or more role="tool" messages — one per
    tool-result event on the document, in chronological order.
    """
```

Rules:

- **User documents:** unchanged.
- **Assistant documents:**
  - Build the assistant `CompletionMessage`:
    - `content` = existing `[ContentPart(text=doc["content"])]` plus the
      attachment / vision-snapshot expansions already in place.
    - `thinking_blocks` = expansion of `doc["thinking_blocks"]` (new) or
      legacy `doc["thinking"]` (string wrapped). **Only when
      `replay_reasoning is True`** (see §6); else omit entirely.
    - `tool_calls` = tool-call events from `doc["events"]`. **Only when
      `replay_tool_history is True`** (see §6); else omit, in which case
      the assistant message reduces to plain content text and we skip
      step (c).
  - For each tool-result event in `doc["events"]` (chronological order):
    - Emit one `CompletionMessage(role="tool", tool_call_id=event.id,
      content=[ContentPart(text=result_content)])`.

**Edge cases handled inline:**

- Assistant turn with thinking but no content and no tool calls
  (refused mid-stream): emit assistant message with `thinking_blocks`
  and empty content `[]`. Most adapters handle this; OpenAI-compat
  routes may need a placeholder space-character — translate_message
  responsibility.
- Tool-call event without matching tool-result (cancelled mid-turn):
  do not emit the assistant message with that tool_call, because the
  resulting prompt would be malformed (`tool_calls` without `tool`
  message reply). Drop the orphan tool-call from the replayed
  `tool_calls` list and log a warning at INFO.
- Multiple tool-call iterations within one turn (the cumulative
  preamble fix from commit `ad38b914`): all iterations land in the
  same `events` list in chronological order; the expansion
  collapses them into one assistant message with all `tool_calls`
  combined plus all resulting `tool` messages. This is technically
  not a faithful replay of the iteration boundaries, but no provider
  rejects it and the model behaves the same as if the iterations were
  serialised.

### 4.3 Call site

Replace the existing loop body:

```python
for doc in selected_history:
    messages.extend(
        _expand_history_doc(
            doc,
            replay_reasoning=reasoning_cap.replay_reasoning,
            replay_tool_history=extras.replay_tool_history,
        )
    )
```

`reasoning_cap` is already resolved a few lines earlier; `extras` is
already passed through to `CompletionRequest`.

---

## 5. Per-adapter changes

### 5.1 Outbound: `_translate_message` push-back matrix

Every HTTP adapter has a `_translate_message` (or equivalent) function
that converts a `CompletionMessage` into the provider wire format.
Today none of them emit thinking blocks. We add adapter-specific
translation for `msg.thinking_blocks`:

| Adapter | Wire format for thinking | Implementation note |
|---|---|---|
| `_openrouter_http.py` (Anthropic models) | `content: [{"type":"thinking","thinking":"…","signature":"…"}, {"type":"text","text":"…"}]` | When `is_anthropic_model(model_id)` AND `msg.thinking_blocks` is non-empty: pre-pend the thinking parts to the content list. Signature is mandatory if present on the block. |
| `_openrouter_http.py` (non-Anthropic) | reasoning_content string | Concatenate `thinking_blocks` into a single `reasoning_content` field on the message; some providers honour it, others ignore. Safe either way. |
| `_xai_http.py` | reasoning_content string | Concatenate, send as `reasoning_content` on the assistant message. xAI ignores unknown fields, no harm if it drops them. |
| `_mistral_http.py` | typed `thinking` parts | Mistral hard-CoT models accept structured thinking objects. Translate each block to `{"type": "thinking", "text": "…"}` and prepend to content. |
| `_chutes_http.py`, `_tensorix_http.py`, `_novita_http.py`, `_nano_gpt_http.py` (non-Anthropic) | reasoning_content string | Same as xAI — concatenate. |
| `_nano_gpt_http.py` (Anthropic models) | Same as OpenRouter Anthropic path | Reuse `is_anthropic_model` check; the nano-gpt route forwards Anthropic-shape content blocks. |
| `_ollama_http.py` | n/a — thinking is conversational, no replay supported by the protocol | Skip the block entirely. Soft-CoT families on Ollama Cloud also have `replay_reasoning=False`, so this never fires in practice. |

### 5.2 Inbound: capture `signature` and `reasoning_details`

`_openrouter_http.py:248-258` and `_nano_gpt_http.py:185-189`:

The current code reads `delta.reasoning` (a string) and ignores
`delta.reasoning_details[*]`. We add a parallel parse path:

```python
# After the existing reasoning_content / reasoning string handling:
details = delta.get("reasoning_details") or []
for d in details:
    # Anthropic forwards: {"type":"thinking","thinking":"…","signature":"…"}
    if d.get("type") == "thinking":
        events.append(ThinkingDelta(
            delta=d.get("thinking") or "",
            signature=d.get("signature"),
            raw=d,
        ))
```

`ThinkingDelta` (in `backend/modules/llm/_adapters/_events.py` or
equivalent) gains optional `signature: str | None` and `raw: dict | None`
fields. The inference loop accumulates these onto the per-turn
thinking buffer.

### 5.3 Persistence at end-of-stream

`backend/modules/chat/_inference.py` — when assembling the final
`save_fn` payload, group the accumulated `ThinkingDelta`s into a
`thinking_blocks: list[dict]` list. Boundary heuristic:

- Provider already delimits blocks (Anthropic does via separate
  `reasoning_details` entries): one block per entry.
- Provider streams as flat string (OpenAI-compat soft-CoT, xAI without
  reasoning_details): one block total, signature `None`.

Persist alongside the existing `thinking: str` (legacy field, becomes
`"".join(b.text for b in blocks)` for human readability).

---

## 6. Capability flags

### 6.1 `ReasoningCapability.replay_reasoning: bool`

Add to `shared/dtos/llm.py`:

```python
class ReasoningCapability(BaseModel):
    kind: Literal["no_reasoning", "optional", "always_on"]
    effort: ReasoningEffortSpec | None = None
    default_on: bool = True
    # NEW. True for hard-CoT families that expect their own prior
    # thinking blocks back in history (Anthropic, xAI Grok reasoning,
    # Mistral Magistral, OpenAI o-series). False for soft-CoT
    # (DeepSeek-R1, Kimi, MiMo, GLM-5) which were trained never to
    # see their own ``<think>`` blocks in subsequent prompts.
    # Default ``False`` — safe-by-default; explicit ``True`` per family.
    replay_reasoning: bool = False
```

Default `False` preserves current behaviour and keeps existing cached
documents readable. We then opt-in per family in
`backend/modules/llm/data/model_capabilities.yaml`:

| Family (substring match in current YAML) | `replay_reasoning` |
|---|---|
| `claude-*` | `True` |
| `grok-*-reasoning`, `grok-4*` | `True` |
| `mistral-magistral*` | `True` |
| OpenAI `o*` series (if reached via any premium provider) | `True` |
| `deepseek-r1*`, `deepseek-v4*` | `False` |
| `kimi-k2*` | `False` |
| `mimo-v25*` | `False` |
| `glm-5*` | `False` |
| Everything else | inherits default `False` |

The orchestrator consults `model_meta.reasoning.replay_reasoning` when
calling `_expand_history_doc` (§4.3).

### 6.2 `ChatSessionExtras.replay_tool_history: bool`

Add to `shared/dtos/chat.py`:

```python
class ChatSessionExtras(BaseModel):
    tools_enabled: bool
    reasoning_mode: Literal["off", "on"]
    reasoning_effort: str | None
    # NEW. When True, past tool-call narration is expanded into
    # assistant(tool_calls) + tool(result) triplets for the next
    # inference (default). When False, the orchestrator collapses
    # past tool-call narration into the assistant's plain content
    # text only — useful for branching off old conversations where
    # the tool results are stale (e.g. last week's web search).
    replay_tool_history: bool = True
```

Default `True`. Exposed via the session-extras endpoint that
`cockpitStore.ts` already calls. Frontend addition: one extra toggle in
the session-cockpit drawer under the existing tool toggles. Out of
scope for this spec to design the UI — backend just needs the field.

---

## 7. Anthropic signature lifetime + fallback

Anthropic does not document an explicit signature lifetime. Observed
behaviour:

- Same conversation, same model, within hours → valid.
- After a model version bump (e.g. `claude-3-5-sonnet-20240620` →
  `-20241022`) → invalid.
- After "long enough" pause → unclear; rejection has been observed in
  the wild.

A branch created days or weeks later is at risk. Strategy:

1. **Capture and replay verbatim.** Default path. Works the vast majority of the time.
2. **Detect provider rejection.** Anthropic returns a 400 with
   `error.type == "invalid_request_error"` and the body mentions
   `signature` or `thinking_block`. The OpenRouter adapter wraps the
   error; the inference layer catches it.
3. **Strip and retry once.** On rejection, the adapter rebuilds the
   request body with `thinking_blocks=[]` on every assistant message
   and re-issues the request. The model loses access to its prior
   reasoning trace but the conversation continues. Emit a
   `ChatStreamWarningEvent` (new, additive) with
   `code="thinking_signature_stripped"` so the UI can optionally toast.

This retry is **adapter-internal**, not orchestrator-driven. It happens
once per request; if the retry also fails, the original error
propagates as today.

---

## 8. Backwards compatibility

- All new DTO fields are optional with sensible defaults.
- Persisted documents without `thinking_blocks` fall back to wrapping
  the legacy `thinking` string (§3.2).
- `replay_reasoning` defaults to `False` — existing models keep their
  current (broken-for-Anthropic-tool-use, but unchanged for everyone
  else) behaviour until their YAML entry is updated.
- `replay_tool_history` defaults to `True`. This *is* a behaviour
  change for existing sessions: subsequent turns now see prior tool
  calls. This is the intended fix. No migration needed — the
  expansion reads from the existing `events` field.
- No MongoDB schema migration. `create_index` for `thinking_blocks`
  is not added (the field is opaque to queries).

---

## 9. Testing strategy

### 9.1 Unit tests

- `tests/unit/test_history_expansion.py` (new) — exercise
  `_expand_history_doc` for:
  - plain user message
  - plain assistant message (no thinking, no tools)
  - assistant with legacy `thinking` string
  - assistant with new `thinking_blocks`
  - assistant with tool calls and matching results
  - assistant with orphan tool call (no result) → drop tool_calls
  - all four `(replay_reasoning, replay_tool_history)` combinations

- `tests/unit/test_completion_message_dto.py` — `ThinkingBlock`
  round-trip via Pydantic dict.

- Per-adapter test (extend existing `test_*_http.py` files):
  - parse path emits `ThinkingDelta` with `signature` when
    `reasoning_details` carries a thinking block.
  - translate path includes thinking blocks in the wire body.

### 9.2 Integration

- `tests/integration/test_replay_anthropic_signature.py` — mock
  OpenRouter `400 invalid_request_error` body; assert single retry
  with stripped thinking blocks. Use the existing LLM test harness
  scenario format (`tests/llm_scenarios/`).

### 9.3 LLM harness scenarios (for manual verification)

Add to `tests/llm_scenarios/`:

- `replay_anthropic_tool_use.json` — multi-turn with tool, run against
  real Claude via OpenRouter, expect no provider error.
- `replay_grok_reasoning_chain.json` — same shape, xAI Grok reasoning.
- `replay_deepseek_no_thinking.json` — DSv4, assert outgoing payload
  does **not** include `<think>` blocks from prior turns.

Chris runs these manually with real keys before merging.

---

## 10. Implementation order

Recommended Subagent task ordering (single agent, sequential within the task):

1. DTO additions (`shared/dtos/inference.py`, `shared/dtos/llm.py`,
   `shared/dtos/chat.py`). Run `pnpm run build` and `uv run python -m
   py_compile shared/dtos/*.py` — no test runs yet.
2. `ThinkingDelta` event addition (`_events.py` or wherever in
   `backend/modules/llm/_adapters/`). Adapters still emit old shape;
   add new optional fields.
3. Per-adapter parse path (`_openrouter_http.py`, `_nano_gpt_http.py`
   first — they handle Anthropic — then the rest).
4. Per-adapter translate path. Same order.
5. Inference loop persistence — group `ThinkingDelta`s into
   `thinking_blocks` at `save_fn` time.
6. `_expand_history_doc` function + orchestrator call site.
7. `model_capabilities.yaml` updates per the §6.1 table.
8. Anthropic strip-and-retry in `_openrouter_http.py` and
   `_nano_gpt_http.py`.
9. All tests.
10. Run the LLM harness scenarios manually (call out to Chris).
11. `pnpm run build` and full pytest pass.

---

## 11. Open product calls — confirmed

- **Q5 (branching + tool side effects):** replay with "not replayed — clone" indicator (already in PRE-BRANCHING). **Not in scope for this spec** — clone-time decision lives in the branching spec.
- **Q6 (signature lifetime):** strip-and-retry on provider reject. **§7.**
- **Q7 (replay_reasoning for DSv4 on Ollama Cloud):** `False`, soft-CoT class. **§6.1 table.**
- **Q8 (effort persistence on branches):** branch's current setting wins. **Branching spec, not here.**
