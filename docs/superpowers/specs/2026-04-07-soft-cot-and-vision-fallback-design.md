# Soft Chain-of-Thought & Vision Fallback — Design

**Date:** 2026-04-07
**Status:** Approved (brainstorming) — pending implementation plan
**Scope:** Two orthogonal persona-level features that extend the capabilities of models which lack native reasoning or vision support.

---

## Background

Chatsune currently supports two model capabilities reported by the LLM adapter layer:

- `supports_reasoning` — whether the model exposes a native thinking/reasoning channel (e.g. via Ollama's `think: true` parameter). When enabled, the adapter emits `ThinkingDelta` events, which the frontend renders in a dedicated thinking block.
- `supports_vision` — whether the model accepts image content parts. When false, attached images are currently replaced by a placeholder text part `[Image: <name> — model does not support vision, image omitted]` in `backend/modules/chat/_orchestrator.py:174-185`.

Two recurring user needs are not yet covered:

1. Some non-reasoning models (notably Mistral) follow Chain-of-Thought instructions reliably when prompted to wrap their reasoning in `<think>…</think>` tags. The previous prototype offered a "Soft CoT" toggle for this and it was well-received. Some users also prefer Soft-CoT over native reasoning even when the model supports the latter.
2. Some users prefer non-multimodal frontier models such as Zhipu's GLM family for reasoning, but want a different model (often Mistral, which has strong image-description and OCR capabilities) to handle image understanding. Open WebUI exposes this as a global setting; user feedback prefers per-persona configuration.

Both features extend the existing system without introducing new modules or breaking existing flows.

---

## Goals

- Allow personas bound to non-reasoning models to opt into a curated Soft-CoT instruction block, with the resulting `<think>…</think>` content surfaced in the existing frontend thinking block.
- Allow personas bound to non-vision models to designate a fallback vision-capable model that produces a textual description of attached images, surfaced transparently to the user as an expandable block in the chat.
- Persist vision descriptions so that history replay does not re-incur GPU cost and so that the rendered chat is stable across reloads.
- Keep both features fully optional, persona-scoped, and backwards compatible.

## Non-Goals

- No global or user-level setting for either feature. Both live on the persona.
- No multi-image batching for the vision fallback call. One image, one call.
- No editable prompt text for Soft-CoT. The instruction block is curated and maintained by the project.
- No automatic detection of which persona "should" use Soft-CoT or vision fallback. The user opts in explicitly.
- No changes to the LLM adapter layer beyond a small helper for non-streaming completion calls if not already available.

---

## Feature A: Soft Chain-of-Thought

### Data model

A new boolean field is added to `PersonaDocument` in `backend/modules/persona/_models.py`:

```python
soft_cot_enabled: bool = False
```

The field is added to `PersonaCreateDto` and `PersonaUpdateDto` in `shared/dtos/persona.py`. The repository persists and reads it like the existing `reasoning_enabled` field. Default is `False` for new personas. Existing personas read with the field absent default to `False`.

### Visibility rule

The Soft-CoT instruction block is appended to the system prompt for an inference call if and only if:

```
not supports_reasoning  OR  (supports_reasoning AND not reasoning_enabled)
```

In words: Soft-CoT is active either when the model has no native reasoning capability at all, or when the model has it but the user has turned Hard-CoT off. When both Hard-CoT and Soft-CoT would be active simultaneously, Hard-CoT wins and the Soft-CoT block is not appended. The `soft_cot_enabled` flag is **never** silently mutated by this rule — it stays in the persona document as the user set it, and the visibility check happens at prompt-assembly time.

The frontend mirrors this rule by rendering the Soft-CoT toggle in a disabled (greyed) state when Hard-CoT is currently active for the persona, with a tooltip explaining why.

### Prompt block

A constant Soft-CoT instruction block is defined in a new file `backend/modules/chat/_soft_cot.py` (exact file location and whether it lives as a Python constant or a loaded `.md` file is an implementation-plan detail). The block instructs the model to wrap all reasoning in `<think>…</think>` before the final answer, and covers two complementary modes:

- **Analytical / step-by-step** for technical and hard-science questions: enumerate assumptions, reason through them in order, verify before concluding.
- **Relational / empathic** for psychology, subtext, mood, and interpretation: read between the lines, consider the user's emotional state, be willing to make associative leaps and bold interpretations.

The block is intentionally a single unified text rather than two togglable sub-blocks. Both modes are compatible — empathic reasoning is itself a step-by-step process — and a single block keeps the UX simple and the prompt maintenance centralised.

The block is not exposed to the user for editing in Phase 1.

### Prompt assembly

`backend/modules/chat/_prompt_assembler.py` gains a new step that, after assembling the existing system prompt layers, appends the Soft-CoT block when the visibility rule is satisfied. The visibility check needs access to:

- the persona's `soft_cot_enabled` flag,
- the persona's `reasoning_enabled` flag (or the session reasoning override, if present),
- the model's `supports_reasoning` capability.

These are already available at the orchestrator level (`_orchestrator.py:201-208`), so the prompt assembler signature is extended accordingly.

### Streaming `<think>` parser

A new component, `SoftCotStreamParser`, sits in the inference pipeline. It consumes the adapter's content delta stream and emits a mixed stream of `ContentDelta` and `ThinkingDelta` events.

**State machine**

Three states: `OUTSIDE` (normal content), `INSIDE_THINK` (text inside a `<think>…</think>` block), and a small fragment buffer for tag detection across chunk boundaries.

- In `OUTSIDE`: scan for `<think>`. Bytes before the tag are emitted as `ContentDelta`. On match, transition to `INSIDE_THINK`.
- In `INSIDE_THINK`: scan for `</think>`. Bytes before the closing tag are emitted as `ThinkingDelta`. On match, transition to `OUTSIDE`.
- Across chunk boundaries: buffer up to a small fragment limit (16 characters) when a partial tag is suspected. If the buffer grows past the limit without resolving into a valid tag start, flush it as content/thinking according to current state.
- If the stream ends inside `INSIDE_THINK` (model forgot to close), flush remaining buffered thinking and finalise normally.
- Lookalike strings (e.g. `<thirsty>`) must not stall the parser — once the buffer cannot be a valid `<think>` or `</think>` prefix, it is flushed.

**Activation**

The parser only runs when Soft-CoT is active for the current inference call (visibility rule satisfied). Reasoning-capable models with Hard-CoT on are unaffected: their `ThinkingDelta`s come directly from the adapter, and no parser sits in between. This avoids double-parsing and accidental interaction with adapters that may emit inline tags as part of normal content for other reasons.

**Integration point**

`backend/modules/chat/_inference.py` currently consumes adapter events directly in its match block (`_inference.py:101-111`). The parser is wired in by wrapping the adapter stream with the parser when Soft-CoT is active, so the existing match block is unchanged. Whether this is implemented as an async generator wrapper or as an inline state machine inside the loop is an implementation-plan detail.

### Robustness

If the model emits no `<think>` tags at all (which happens with weak or heavily quantised models), all output flows through as normal `ContentDelta`. No error, no warning. The user can observe the missing thinking block and either accept it or pick a stronger model — the displayed quantisation level on the model card already gives them the relevant signal.

### Events

No new event types. The existing `ChatThinkingDeltaEvent` carries the parsed thinking content.

---

## Feature B: Vision Fallback Model

### Data model: Persona

A new optional field is added to `PersonaDocument`:

```python
vision_fallback_model: str | None = None  # unique model ID, e.g. "ollama_cloud:mistral-large"
```

The field is added to the persona DTOs and persisted via the existing repository methods. It is fully nullable and freely settable to `None` to remove a previously selected fallback. The format is the existing model unique ID `<provider_id>:<model_slug>` (see INSIGHTS.md INS-004).

### Data model: File-level cache

The storage module gains a new field on its file documents:

```python
vision_descriptions: dict[str, VisionDescriptionEntry]
# key: vision model unique ID
# value: { text: str, model_id: str, created_at: datetime }
```

Two new public functions on the storage module:

- `get_cached_vision_description(file_id: str, model_id: str) -> str | None`
- `store_vision_description(file_id: str, model_id: str, text: str) -> None`

Cache entries have no TTL and are never invalidated. A given (file, model) pair always produces the same description for our purposes — re-running adds cost without value.

### Data model: Message-level snapshot

The chat message document gains a new optional field:

```python
vision_descriptions_used: list[VisionDescriptionSnapshot] | None
# each entry: { file_id, display_name, model_id, text }
```

This snapshot is written at the moment the message is sent for inference and captures whichever description was actually used. It is independent of the file-level cache: if the cache is later invalidated, or the persona's `vision_fallback_model` changes, the historical message still renders with the description it was created with. This guarantees a stable chat history.

### Orchestrator integration

The current code path in `_orchestrator.py:174-185` is replaced. For each image attachment on the new user message, when `not supports_vision`:

1. Read `vision_fallback_model_id = persona.get("vision_fallback_model")`.
2. **No fallback configured** → keep the existing placeholder text part `[Image: <name> — model does not support vision, image omitted]`. This preserves the current behaviour for personas that don't opt in.
3. **Fallback configured, cache hit** → append `ContentPart(type="text", text=cached_description_with_label)` and record the snapshot in `vision_descriptions_used`. No vision call.
4. **Fallback configured, cache miss** → invoke the `vision_fallback_runner` (see below). On success: store in cache, append text part, record snapshot. On final failure: emit the warning event, append a placeholder text part with an error marker, and let the main inference run normally.

Multiple images in a single message are processed sequentially with one vision call per image. The order in which descriptions are appended to the message matches the order of the original attachments.

The text-part wrapper format (label, separator) mirrors the existing text-attachment format at `_orchestrator.py:186-191` so that downstream models see image descriptions as just another attachment.

### Vision fallback runner

A new component (file location TBD by implementation plan) performs the vision call.

- **Inputs**: image bytes + media type, target vision model unique ID.
- **Call**: a single non-streaming completion against the configured model. System prompt is a fixed, short instruction along the lines of "Describe this image in detail for a downstream assistant that cannot see it. Include objects, text, layout, and mood." User message contains only the image as an `image` content part.
- **Retry policy**: on any adapter exception, retry exactly once. The single retry exists specifically to handle Ollama Cloud cold-start failures, which occasionally fail the first call against a model that has not been used recently.
- **Failure**: after the retry fails, raise a typed exception that the orchestrator catches and converts into the warning event + placeholder behaviour.
- **Reuse**: this runner uses the existing LLM module public API (`backend/modules/llm/__init__.py`) and does not bypass the adapter abstraction.

### Frontend visibility

A new event type is added in `shared/events/chat.py`:

```python
class ChatVisionDescriptionEvent(BaseEvent):
    correlation_id: str
    file_id: str
    display_name: str
    model_id: str
    status: Literal["pending", "success", "error"]
    text: str | None         # set when status == "success"
    error: str | None        # user-facing message when status == "error"
```

A corresponding constant `Topics.CHAT_VISION_DESCRIPTION` is added in `shared/topics.py`.

The orchestrator emits this event up to twice per image: once with `status="pending"` immediately before invoking the vision runner (so the frontend can show a spinner), and once with `status="success"` or `status="error"` after the call resolves. On cache hit, only the success event is emitted (no pending event needed).

The frontend renders an expandable description block beneath the image thumbnail in the user message. Block states map directly to the event status:

- **pending**: spinner with vision model name
- **success**: collapsible block showing the description text and model name
- **error**: warning icon with the user-facing error message and a hint to resend the message

The block is keyed by `(correlation_id, file_id)` and subscribes to `Topics.CHAT_VISION_DESCRIPTION` on the WebSocket event bus.

### History replay

When a session's history is loaded, the message renderer reads `vision_descriptions_used` from each message document and renders the description block in the `success` state directly from the snapshot. No live event is needed — the snapshot is part of the loaded message.

Server-side, when rebuilding the inference message list from history (`_orchestrator.py:153-162`), historical attachments with a snapshot description are converted into text content parts using the snapshot text. This means future turns in the same conversation can refer back to "the image you saw earlier" without re-running the vision model.

---

## Frontend impact

### Persona editor

In the persona create / edit modal, two new fields are added:

1. **Soft Chain-of-Thought toggle** — always rendered. Disabled (greyed) with tooltip when the persona's bound model has `supports_reasoning=true` and `reasoning_enabled=true`. Bound to `soft_cot_enabled`.
2. **Vision fallback dropdown** — rendered only when the persona's bound model has `supports_vision=false`. Options: "No fallback" plus all available models with `supports_vision=true`, grouped by provider. Clearable. Bound to `vision_fallback_model`.

Both fields are persisted via the existing persona update flow. No new endpoints. The DTOs `PersonaCreateDto` and `PersonaUpdateDto` in `shared/dtos/persona.py` are extended with the two new optional fields.

### Chat stream

- **Soft-CoT**: zero frontend changes. The existing thinking block already consumes `ChatThinkingDeltaEvent`, regardless of whether the deltas originate from the adapter or the new parser.
- **Vision description block**: a new small component beneath the image thumbnail in user messages. Subscribes to `Topics.CHAT_VISION_DESCRIPTION` and renders the three states described above. Reads from `vision_descriptions_used` for historical messages.

### State

No new stores. No new routes. Both features integrate into the existing persona state slice and the existing WebSocket event bus.

---

## Testing

### Soft-CoT

1. **Parser unit tests** (`tests/test_soft_cot_parser.py`):
   - Whole `<think>…</think>` block in one chunk → one `ThinkingDelta`, no `ContentDelta`.
   - Tag splitting across chunk boundaries: `<thi`, `nk>hello`, `</thi`, `nk>world` → `ThinkingDelta("hello")` + `ContentDelta("world")`.
   - Multiple consecutive `<think>` blocks → multiple cleanly separated `ThinkingDelta`s.
   - Stream with no tags at all → all output emitted as `ContentDelta`.
   - Lookalike tag (`<thirsty>`) → emitted as normal content, parser does not stall.
   - Open `<think>` with no closing tag before stream end → buffered thinking is flushed cleanly on finalise.

2. **Prompt assembler tests** (extending `tests/test_prompt_assembler.py` if it exists, or a new file):
   - Non-reasoning model + Soft-CoT on → block appended.
   - Reasoning model + Hard-CoT on + Soft-CoT on → block **not** appended.
   - Reasoning model + Hard-CoT off + Soft-CoT on → block appended.

   Assertions check for a stable marker substring in the assembled prompt, never the full block text — that lets us iterate on the prompt without breaking tests.

3. **Manual integration via LLM test harness**: a scenario file at `tests/llm_scenarios/soft_cot_mistral.json` runs the assembled prompt against a real Mistral model with one analytical and one empathic question. Used during prompt tuning, not in CI.

### Vision fallback

1. **Storage cache unit tests** (`tests/test_storage_vision_cache.py`):
   - `store` then `get` returns the stored text.
   - Miss returns `None`.
   - Two different model IDs for the same file coexist independently.

2. **Orchestrator tests** (`tests/test_chat_orchestrator_vision_fallback.py`) with a mocked LLM adapter layer:
   - Non-vision main model + no fallback configured → existing placeholder behaviour, no vision call.
   - Non-vision main model + fallback configured + cache hit → no vision call, text part appended, snapshot recorded.
   - Cache miss → exactly one vision call, cache written, snapshot written, text part appended.
   - Vision call fails twice (initial + retry) → warning event emitted, placeholder text part with error marker appended, main stream runs normally.
   - Vision call fails once then succeeds → success event emitted, normal flow.
   - Multiple images in one message → one vision call per image, all snapshots recorded in order.
   - Main model **with** vision support → fallback setting ignored entirely, normal multimodal flow.

3. **History replay test**: load a message that has `vision_descriptions_used` set, run the inference message-list build, assert that text content parts are populated from the snapshot and no vision call is invoked.

4. **Manual integration via LLM test harness**: a scenario file at `tests/llm_scenarios/vision_fallback_mistral.json` runs a GLM persona with Mistral as vision fallback against a flower image (the canonical test case for vision quality).

### What we deliberately do not test

- The exact wording of vision model output. Model output is not reproducible.
- The exact wording of the Soft-CoT prompt block in equality assertions. Tests check for a stable marker substring only.

---

## Module boundaries

This design respects the strict module boundaries from `CLAUDE.md`:

- The chat module owns the prompt assembler, the inference runner, the streaming parser, the orchestrator, and the new vision fallback runner.
- The persona module owns its document, its DTOs, and its repository — no other module reads `vision_fallback_model` directly; the orchestrator obtains it via the existing `get_persona` public API.
- The storage module owns the file cache fields and exposes the two new public functions for vision description caching.
- The LLM module is consumed via its existing public API for the vision fallback completion call. No adapter internals are touched.
- All new shared contracts (persona DTO fields, the new event class, the new topic constant) live in `shared/`.

No cross-module DB access. No magic event-type strings. No imports of `_`-prefixed internals across module boundaries.

---

## Out of scope (future work)

- User-editable Soft-CoT prompt overrides per persona. If the curated block proves insufficient, we can add an optional `soft_cot_prompt_override: str | None` field later as a non-breaking change.
- Global default vision fallback model at the user level. Could be added as a fallback-of-the-fallback if there is demand, but Phase 1 is strictly per-persona.
- Vision fallback for image content in message history that predates this feature. Existing messages with omitted images stay as they are. Re-sending generates a new message that uses the new flow.
- Multi-image batching for the vision call. Current providers and models handle single images well, and per-image calls produce cleaner snapshots and clearer error attribution.
