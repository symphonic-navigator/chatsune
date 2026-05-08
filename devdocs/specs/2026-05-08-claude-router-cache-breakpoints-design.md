# Claude Router Cache Breakpoints — Design

**Date:** 2026-05-08
**Status:** Draft
**Reverses:** INS-032 (Phase-1 pass-through decision)

---

## 1. Context & Problem

INS-032 (2026-04-28) recorded a Phase-1 decision: pass-through cache
behaviour through the LLM routers, no `cache_control` markers. The
rationale was that adding markers requires content-block-level
plumbing the OpenAI-compatible adapters did not need yet, and
auto-prefix-caching covered the bulk of realistic traffic on
non-Anthropic providers.

Beta testers have explicitly asked for **prompt caching on Claude
models routed through OpenRouter and nano-gpt**. Anthropic models
require explicit `cache_control` markers — without them, every turn
on a long-running conversation pays full input price for the entire
prefix. For chat companion sessions that run dozens of turns, this is
material cost.

This design reverses INS-032 specifically for **Anthropic models
behind LLM routers** (OpenRouter and nano-gpt). All other routes —
xAI, Mistral, Ollama, Community, and non-Anthropic models on the
routers — remain pass-through.

## 2. Goals & Non-Goals

**Goals**
- Per-persona TTL choice (Off / 5 minutes / 1 hour) for Claude models.
- Automatic breakpoint placement that maximises cache hit rate on
  rolling chat conversations without exposing the user to the
  underlying mechanics.
- Consistent behaviour across both routers (OpenRouter and nano-gpt).
- Real-traffic observability so the strategy can be validated
  empirically and refined later.

**Non-goals**
- Native Anthropic adapter (no plans to add one — the routers are the
  product story for Claude access; users explicitly want anonymisation
  via routers).
- Cache support for tool definitions (Chatsune tool payloads are
  small and changeable; not worth the complexity in v1).
- Pre-heat / cache-warming on conversation load (organic on first
  user turn — see §5).
- Other vendor cache mechanisms (xAI, Gemini auto-caching, etc.).
  Field naming is vendor-scoped to leave room for future additions
  without conflicts.

## 3. Architecture & Data Flow

```
PersonaDto             chat module             CompletionRequest        Adapter
(anthropic_       →    (resolves persona,  →   (anthropic_         →    OR / nano-gpt
 cache_ttl)             maps into req)          cache_ttl flag)          → vendor detection
                                                                         → strategy lib
                                                                         → marker emission
```

**Field placement**
- `PersonaDto.anthropic_cache_ttl: Literal["off","5m","1h"] = "off"`
- `CreatePersonaDto.anthropic_cache_ttl` (same default)
- `UpdatePersonaDto.anthropic_cache_ttl: Literal["off","5m","1h"] | None = None`
- `CompletionRequest.anthropic_cache_ttl: Literal["off","5m","1h"] = "off"`

Default `"off"` means existing persona documents and existing
in-flight requests deserialise unchanged (backwards-compatible per
CLAUDE.md §Data-Model Migrations — no migration script needed).

The vendor-scoped name (`anthropic_cache_ttl`) leaves room for
future per-vendor cache fields (`xai_cache_ttl`,
`gemini_cache_strategy`, etc.) without collision.

**Strategy lib location**
- New module: `backend/modules/llm/_adapters/_anthropic_cache.py`
- Pure functions, importable by both routers:
  - `is_anthropic_model(model_id: str) -> bool`
  - `compute_cache_markers(messages, ttl) -> list[CacheMarker]`
- Adapter responsibility: detect Anthropic + ttl != off, run the
  strategy lib, emit `cache_control` markers in the adapter's own
  message-translation step.

Other adapters (xAI, Mistral, Ollama, Community) are not modified.

## 4. Vendor Detection

The two routers expose Claude models with inconsistent slug shapes:

- OpenRouter: `anthropic/claude-3-7-sonnet-20250219`,
  `anthropic/claude-opus-4-1`, occasionally `~anthropic/claude-…`
  (latter prefix shape observed in real OR catalogue).
- nano-gpt: `claude-3-7-sonnet-20250219` (no vendor prefix).

Detection rule — **strip everything before the last `/` and regex on
the remainder**:

```python
_CLAUDE_RE = re.compile(r"claude.*\b(haiku|sonnet|opus)\b", re.IGNORECASE)

def is_anthropic_model(model_id: str) -> bool:
    tail = model_id.rsplit("/", 1)[-1]
    return bool(_CLAUDE_RE.search(tail))
```

**Allowlist scope:** only `haiku`, `sonnet`, `opus`. Older
`claude-instant-*` slugs do not match (they did not support
`cache_control`, so this is correct). Hypothetical future Claude
families (e.g. `claude-mythos`) are deliberately excluded — when
Anthropic ships a new family, this is a five-line update and a
deliberate decision, not silent inclusion.

**Negative cases that must not match:** `gpt-4`, `llama-3.3-70b`,
`mistral-large`, `claude-instant-1`, `meta/llama-claude-skin`.

## 5. Breakpoint Placement Strategy

### 5.1 Mental model

Anthropic prompt caching uses **longest-prefix-match for reads**: on
each request, Anthropic finds the longest cached prefix in the
account that matches the start of the current request, charging
those tokens at 0.1×. `cache_control` markers in the request
determine **where new caches can be written** (1.25× for 5m, 2× for
1h), not where reads happen.

A rolling-tail strategy therefore yields ~85% input savings per
turn, not ~50%, because:
- Read: the previous turn's cache covers ~98% of the current
  request's prefix → 0.1× × bulk.
- Write: the new tail marker writes only the **delta** beyond the
  previous cache → 1.25× × small.
- Uncached: only the new user message after the tail marker pays
  full 1× rate.

### 5.2 Marker layout

Up to 4 cache breakpoints per Anthropic request. Chatsune uses three
deliberately:

| Marker             | Position                                                | TTL              |
|--------------------|---------------------------------------------------------|------------------|
| System             | Index 0 (system message), if present                    | Always 1h        |
| Block-boundary     | Last crossed `BLOCK_SIZE`-aligned message index         | Always 1h        |
| Rolling tail       | `len(messages) - 2` (last stable assistant message)     | User's choice    |
| (4th slot)         | Deliberately unused — reserved for future use           | —                |

`BLOCK_SIZE = 8`. The block-boundary marker is **always placed
regardless of user's TTL choice** because it provides a long-pause
fallback essentially for free (block writes only happen every 8
messages, amortised cheaply across active turns).

The user's `anthropic_cache_ttl` choice **only changes the rolling
tail's TTL**. System and block markers are constant 1h.

### 5.3 Pseudo-code

```python
from dataclasses import dataclass
from typing import Literal

CacheTtl = Literal["off", "5m", "1h"]
BlockTtl = Literal["5m", "1h"]
BLOCK_SIZE = 8

@dataclass(frozen=True)
class CacheMarker:
    message_index: int
    ttl: BlockTtl

def compute_cache_markers(
    messages: list[CompletionMessage],
    ttl: CacheTtl,
) -> list[CacheMarker]:
    if ttl == "off" or not messages:
        return []
    markers: list[CacheMarker] = []

    # 1. System: always 1h
    if messages[0].role == "system":
        markers.append(CacheMarker(message_index=0, ttl="1h"))

    # 2. Block-boundary: always (even in 5m mode), 1h
    n = len(messages)
    last_block_end = (n // BLOCK_SIZE) * BLOCK_SIZE - 1
    if last_block_end > 0 and last_block_end < n - 1:
        if not any(m.message_index == last_block_end for m in markers):
            markers.append(CacheMarker(message_index=last_block_end, ttl="1h"))

    # 3. Rolling tail: TTL = user's choice
    if len(messages) >= 2:
        tail_index = len(messages) - 2
        if not any(m.message_index == tail_index for m in markers):
            markers.append(CacheMarker(message_index=tail_index, ttl=ttl))

    return markers
```

### 5.4 What this strategy does NOT do

- **No pre-heat on conversation load.** When a user opens an existing
  chat, no API call is made. The first user message naturally carries
  markers that include the historic prefix, triggering a cache write
  on that turn. Pre-heating would charge cache writes for sessions
  the user might only inspect briefly.

- **No carry-forward of expired markers.** We rely on Anthropic's
  longest-prefix-match for reads. Stale markers are not re-emitted
  in current request just to "extend" them.

- **No per-conversation block-size tuning.** Static `BLOCK_SIZE = 8`.
  If observability data later shows the boundary should be elsewhere,
  this is a one-line change, no migration.

## 6. Marker Emission (Adapter Layer)

Both `_openrouter_http.py` and `_nano_gpt_http.py` use the OpenAI-compat
chat-completions API with `cache_control` extension on content blocks.
The current `_translate_message()` emits a plain string for text-only
messages and a content-block list only for messages with images. To
attach `cache_control`, content **must** be in the list form.

### 6.1 Updated `_translate_message`

```python
def _translate_message(
    msg: CompletionMessage,
    *,
    cache_control: dict | None = None,  # e.g. {"type": "ephemeral", "ttl": "1h"}
) -> dict:
    text_parts = [p for p in msg.content if p.type == "text" and p.text]
    image_parts = [p for p in msg.content if p.type == "image" and p.data]

    if cache_control is None and not image_parts:
        # Existing path — plain string content (more cache-friendly
        # for adapters without explicit cache markers).
        content: str | list[dict] = "".join(p.text or "" for p in text_parts)
    else:
        content = []
        for p in text_parts:
            content.append({"type": "text", "text": p.text or ""})
        for p in image_parts:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{p.media_type};base64,{p.data}"},
            })
        if cache_control and content:
            # Anthropic convention: cache_control on the LAST content
            # block of the cached message (the prefix up to and
            # including this block is what gets cached).
            content[-1]["cache_control"] = cache_control

    result: dict = {"role": msg.role, "content": content}
    if msg.tool_calls:
        result["tool_calls"] = [...]
    if msg.tool_call_id is not None:
        result["tool_call_id"] = msg.tool_call_id
    return result
```

### 6.2 Updated `_build_chat_payload`

```python
def _build_chat_payload(request: CompletionRequest, ...) -> dict:
    markers: list[CacheMarker] = []
    if (
        is_anthropic_model(request.model)
        and request.anthropic_cache_ttl != "off"
    ):
        markers = compute_cache_markers(
            request.messages, request.anthropic_cache_ttl,
        )

    cc_by_index = {
        m.message_index: _to_cache_control(m.ttl)
        for m in markers
    }

    payload = {
        "model": request.model,
        "stream": True,
        "stream_options": {"include_usage": True},
        "messages": [
            _translate_message(m, cache_control=cc_by_index.get(i))
            for i, m in enumerate(request.messages)
        ],
        ...
    }
    return payload


def _to_cache_control(ttl: BlockTtl) -> dict:
    # OpenAI-compat → Anthropic translation expects ephemeral type.
    # 5m is implicit when ttl is omitted; 1h requires explicit ttl="1h".
    if ttl == "1h":
        return {"type": "ephemeral", "ttl": "1h"}
    return {"type": "ephemeral"}
```

The OR adapter and nano-gpt adapter will each carry their own copy of
the marker emission logic — consistent with the existing pattern of
both adapters cloning their SSE handling. Centralisation is tracked
separately under the OpenAI-compat-SSE-refactor project (memory:
`project_openai_compat_refactor.md`); not pulled forward here.

### 6.3 Tools / tool definitions

Out of scope for v1. Anthropic supports `cache_control` on tool
definitions, but in OpenAI-compat the `tools` field is a top-level
sibling of `messages`, not embedded in messages. Cache support there
would require a separate translator. Chatsune tool payloads are
small in current usage; revisit if observability data shows it
matters.

## 7. UI

Single change to the persona edit form. The control sits directly
under the model picker.

**Conditional visibility**
- Only rendered when the currently selected model passes
  `is_anthropic_model` on the **frontend**. Non-Anthropic model
  selected → entire control is hidden (not greyed out).
- Frontend mirrors the same regex as backend for parity.

**Persistence semantics**
- User picks Anthropic model → control appears, default `"off"`.
- User picks non-Anthropic model → control hidden, persisted value
  is **kept** (not reset).
- User switches back to Anthropic → previously-persisted value is
  shown again.
- Backend silently ignores `anthropic_cache_ttl` for non-Anthropic
  model requests — no errors, no warnings.

**Control form**
- Single-select dropdown (per `feedback_filter_controls.md`:
  dynamic option sets favour dropdowns over chip clusters).
- Label: `Prompt cache`.
- Options: `Off`, `5 minutes`, `1 hour`.
- Helper text (small, dimmed): `Reduces input cost on repeated
  context. Off by default.`

**Mock**

```
┌─ Model ──────────────────────────────────────┐
│ ▼ openrouter:anthropic/claude-sonnet-4.5     │
└──────────────────────────────────────────────┘

┌─ Prompt cache ───────────────────────────────┐
│ ▼ 5 minutes                                  │
└──────────────────────────────────────────────┘
  Reduces input cost on repeated context.
  Off by default.

┌─ Temperature ────────────────────────────────┐
│ ●─────────  0.8                              │
└──────────────────────────────────────────────┘
```

## 8. Migration Considerations

No migration script required.

- New optional field with default `"off"` on `PersonaDto` and
  `CompletionRequest` deserialises existing documents and in-flight
  requests unchanged (per CLAUDE.md §Data-Model Migrations).
- No index changes.
- No DTO renames.
- No event-shape changes.

## 9. Testing

### 9.1 Unit tests (host, no Docker required)

`tests/llm/test_anthropic_cache.py`:
- `is_anthropic_model`:
  - Positive: `anthropic/claude-3-7-sonnet-20250219`,
    `~anthropic/claude-opus-4-1`, `claude-haiku-4-5`,
    `anthropic/claude-3.5-sonnet-vision`.
  - Negative: `openai/gpt-4`, `meta/llama-3.3-70b`,
    `mistral-large-latest`, `anthropic/claude-instant-1`,
    `meta/llama-claude-skin` (regex must not match without
    haiku/sonnet/opus tail).
- `compute_cache_markers`:
  - `ttl="off"` → empty list.
  - 1 user message only → only system marker (no tail, no block).
  - 5 messages, ttl=5m → System + Tail (no block, n < BLOCK_SIZE).
  - 22 messages, ttl=5m → System + Block@15 (1h) + Tail@20 (5m).
  - 22 messages, ttl=1h → System + Block@15 (1h) + Tail@20 (1h).
  - Edge: collision avoidance (system vs block, block vs tail) → no
    duplicate markers at the same index.
  - Empty message list → empty marker list.

### 9.2 Adapter integration tests (host, mocked HTTP)

`tests/llm/adapters/test_openrouter_cache.py` and
`test_nano_gpt_cache.py` (parallel coverage):
- Anthropic model + `ttl="5m"` → outgoing payload carries
  `cache_control` on the right indices: system marker has
  `{"type": "ephemeral", "ttl": "1h"}`, block marker (when present)
  has `{"type": "ephemeral", "ttl": "1h"}`, tail marker has
  `{"type": "ephemeral"}` (no ttl field; 5m is the implicit default).
- Anthropic model + `ttl="1h"` → same as above except the tail
  marker also carries `{"type": "ephemeral", "ttl": "1h"}`.
- Anthropic model + `ttl="off"` → no `cache_control` anywhere in
  payload.
- Non-Anthropic model + `ttl="5m"` → no `cache_control` anywhere
  (TTL silently ignored).
- Image-content message at marker index → `cache_control` lands on
  the **last** content block (the image_url block).
- Plain-text message at marker index → content list is materialised
  even though no images are present, `cache_control` on last (only)
  text block.

Tests must run on host without MongoDB (per
`feedback_db_tests_on_host.md`); pure-function strategy tests have
no DB dependency, adapter tests use httpx mock.

### 9.3 Manual verification (real device)

Per `feedback_manual_test_sections_in_specs.md`:

1. Persona with `anthropic/claude-sonnet-4.5` via an OpenRouter
   connection, `anthropic_cache_ttl = 5m`. Send 3–4 turns of normal
   chat.
2. Backend logs (grep `anthropic_cache`): from turn 2 onwards,
   `cache_read_input_tokens > 0` and `cache_creation_input_tokens`
   should be small (delta, not full prefix).
3. Same persona, set `anthropic_cache_ttl = 1h`. Send 8+ messages
   to cross the first block boundary. Pause ~10 minutes. Send
   another message. Logs should show high `cache_read_input_tokens`
   on the post-pause turn (block survived) with small write.
4. Switch the persona's connection to nano-gpt with a Claude model.
   Repeat steps 1–3. Both routers must yield comparable cache
   behaviour.
5. Switch persona to a non-Anthropic model (e.g., GPT-4o via
   OpenRouter). UI control must vanish; backend logs must show no
   `anthropic_cache` entries.

## 10. Observability

Single new structured log line emitted by each router adapter on
the terminal `usage` chunk:

```python
_log.info(
    "anthropic_cache model=%s ttl=%s "
    "cache_read=%d cache_creation=%d input=%d",
    payload.get("model"),
    request.anthropic_cache_ttl,
    usage.get("cache_read_input_tokens", 0),
    usage.get("cache_creation_input_tokens", 0),
    usage.get("prompt_tokens", 0),
)
```

This is the validation surface for "the strategy actually delivers".
After 1–2 days of real beta traffic, hit-rate and write-cost ratios
become visible via `grep anthropic_cache` over the backend logs and
inform any subsequent strategy tuning (block size, tail position,
whether to use the 4th breakpoint slot for a secondary anchor,
etc.).

No frontend exposure of cache token counts in v1. May surface in a
future debug / admin view.

## 11. Open Questions / Future Work

- **Block size tuning.** `BLOCK_SIZE = 8` is a first guess. Real
  traffic data may indicate 4 or 16 is better. Single-line change,
  no migration impact.
- **4th breakpoint use.** Deliberately reserved. If observability
  reveals patterns where a secondary anchor (e.g., between system
  and block-boundary) helps — for example, very long
  system-prompt-plus-prelude personas — wire it up later.
- **Tools cache_control.** Out of scope for v1; revisit if
  observability shows tool-definition repetition is meaningfully
  contributing to uncached input cost.
- **OpenAI-compat-SSE refactor.** The duplicated marker emission
  logic in OR and nano-gpt is acceptable now. The shared-helper
  extract is tracked under the existing OpenAI-compat refactor
  project (memory `project_openai_compat_refactor.md`).
