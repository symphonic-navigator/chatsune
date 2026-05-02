# Master System Prompt in Internal LLM Calls — Design

**Date:** 2026-05-02
**Status:** Approved (pre-implementation)
**Scope:** Backend only

---

## Motivation

Today the admin-managed master system prompt is only injected by the chat
prompt assembler (`backend/modules/chat/_prompt_assembler.py:82-85`). All
internal server-side LLM calls — the three background-job handlers and the
vision-fallback helper — bypass it entirely.

This causes two concrete problems with open-source models:

1. The server-wide guardrail / persona-loosening directives the admin sets
   (e.g. NSFW allowance, refusal-suppression, persona-tone framing) do not
   apply to memory extraction, memory consolidation, title generation, or
   vision fallback. Models then refuse to summarise, extract, title, or
   describe content that was perfectly fine inside the chat itself.
2. The upcoming **compact and continue** feature will rely on the same
   guardrail-loosening to summarise long conversations without the
   summariser model refusing on policy grounds. Without master-prompt
   injection in background jobs, that feature cannot land cleanly.

The fix is to route the master prompt into every internal LLM call as a
real `system`-role message, identical in semantics to how chat already
does it.

---

## Non-Goals

- No change to the chat orchestrator's prompt assembly. It already injects
  the master prompt and stays as-is.
- No new admin-facing UI. The master prompt continues to be set via the
  existing `PUT /api/settings/system-prompt` endpoint.
- No DB schema change. No data migration. The settings document stays
  unchanged.
- No change to per-persona, per-model, or about-me prompt layers. Those
  remain chat-only.
- The LLM-harness (`backend/llm_harness/`) is a debug tool and stays
  unaffected — its purpose is to issue raw, unmodified LLM calls.

---

## Affected Call-Sites

Four server-side LLM call-sites are changed:

| Call-site | File | Type |
|---|---|---|
| Memory extraction | `backend/jobs/handlers/_memory_extraction.py` | Background job |
| Memory consolidation | `backend/jobs/handlers/_memory_consolidation.py` | Background job |
| Title generation | `backend/jobs/handlers/_title_generation.py` | Background job |
| Vision fallback | `backend/modules/chat/_vision_fallback.py` | Synchronous in-line helper |

Note: vision fallback is not a background job in the queue sense — it
runs synchronously inside the chat request flow. It is included here
because the same open-source-guardrail argument applies, and because it
already uses a `system`-role message which we restructure anyway.

---

## Design

### 1. Helper in the settings module

The master prompt is owned content of the `settings` module. The
finished-to-`CompletionMessage` builder is exposed via the module's
public API:

```python
# backend/modules/settings/__init__.py

from dataclasses import dataclass
from shared.dtos.inference import CompletionMessage

@dataclass(frozen=True)
class AdminSystemPrompt:
    """A ready-to-prepend admin system message plus its raw text.

    raw_text excludes the <systeminstructions> wrapper and is suitable for
    token-budget reservation arithmetic.
    """
    message: CompletionMessage
    raw_text: str

async def get_admin_system_message() -> AdminSystemPrompt | None:
    """Return the admin master prompt as a system-role CompletionMessage,
    wrapped in <systeminstructions priority="highest">…</systeminstructions>,
    or None if no admin prompt is set or it is empty / whitespace-only.

    The admin prompt is a TRUSTED source and is NOT sanitised, matching the
    chat prompt assembler's treatment.
    """
```

Wrapping is identical to `_prompt_assembler.py:82-85`:

```
<systeminstructions priority="highest">
{stripped admin prompt}
</systeminstructions>
```

`raw_text` is the **stripped admin prompt without the wrapper**, used by
callers to feed `check_and_reserve_budget` so the daily-budget reservation
includes the master-prompt cost.

### 2. Integration pattern — three job handlers

Each of `_memory_extraction.py`, `_memory_consolidation.py`, and
`_title_generation.py` follows the same pattern:

```python
from backend.modules.settings import get_admin_system_message

admin = await get_admin_system_message()
prefix_messages = [admin.message] if admin else []
admin_text_for_budget = (admin.raw_text + "\n") if admin else ""

request = CompletionRequest(
    model=model_slug,
    messages=prefix_messages + [<existing messages>],
    ...
)

await check_and_reserve_budget(
    redis,
    job.user_id,
    admin_text_for_budget + <existing prompt_text>,
)
```

Concretely:

| Handler | Existing messages | After change |
|---|---|---|
| Memory extraction | `[user(extraction_prompt)]` | `[system(admin)?, user(extraction_prompt)]` |
| Memory consolidation | `[user(consolidation_prompt)]` | `[system(admin)?, user(consolidation_prompt)]` |
| Title generation | `[user(msg1), assistant(msg2), …, user(_TITLE_INSTRUCTION)]` | `[system(admin)?, user(msg1), assistant(msg2), …, user(_TITLE_INSTRUCTION)]` |

Where `system(admin)?` is included **only** when an admin prompt is
configured. If no admin prompt is set, the request structure is byte-for-byte
identical to today.

The `record_handler_tokens` call on the job-handler side likewise needs
to receive the admin-inclusive prompt text so that token bookkeeping is
honest.

### 3. Integration — vision fallback (restructured)

The vision-fallback helper is restructured so its message layout matches
how a user would interact with a vision model: text-and-image in a single
`user`-role message, with the system role reserved for the master prompt.

**Before** (`backend/modules/chat/_vision_fallback.py:67-82`):

```python
messages=[
    CompletionMessage(role="system", content=[ContentPart(type="text", text=_VISION_FALLBACK_SYSTEM_PROMPT)]),
    CompletionMessage(role="user",   content=[ContentPart(type="image", data=image_data, media_type=media_type)]),
],
```

**After:**

```python
admin = await get_admin_system_message()
prefix = [admin.message] if admin else []

messages=[
    *prefix,
    CompletionMessage(
        role="user",
        content=[
            ContentPart(type="text",  text=_VISION_FALLBACK_USER_INSTRUCTION),
            ContentPart(type="image", data=image_data, media_type=media_type),
        ],
    ),
],
```

The constant `_VISION_FALLBACK_SYSTEM_PROMPT` is renamed to
`_VISION_FALLBACK_USER_INSTRUCTION` and reworded into a first-person
request that reads naturally as a user instruction. Functional content is
preserved (subjects, objects, layout, visible text, colours, mood; no
interpretation).

Suggested wording:

> "Please describe this image in detail: subjects, objects, layout, any
> visible text, colours, and the overall mood. Be specific and concrete.
> Do not add interpretation or advice — only what is in the image."

Vision fallback does not use the daily-budget reservation pipeline, so no
budget-arithmetic adjustment is needed there.

### 4. Trust boundary

The admin prompt is treated as **trusted, not sanitised**. This matches
the existing chat prompt assembler. Rationale: only an authenticated
admin can set the master prompt, the value is stored in the platform's
own settings collection, and the chat already trusts it the same way.

### 5. Edge cases

- **Admin prompt unset:** `get_admin_system_message()` returns `None`.
  All four call-sites fall back to their current request structure
  exactly. No `system` message is emitted.
- **Admin prompt whitespace-only:** treated as unset (returns `None`).
- **Admin prompt set after job enqueued, before job runs:** the job uses
  the value at the moment it executes, not at enqueue time. This is the
  intended behaviour (admin prompt is a live setting, not a per-job
  snapshot).
- **Concurrency:** the master prompt is read fresh per LLM call. There is
  no caching or memoisation introduced by this change.

---

## Module-Boundary Compliance

This design respects CLAUDE.md hard requirement #1 (module boundaries):

- The new helper lives in the `settings` module's public API
  (`backend/modules/settings/__init__.py`).
- Callers (`backend/jobs/handlers/*`, `backend/modules/chat/_vision_fallback.py`)
  import from `backend.modules.settings` only — no underscored internals.
- The settings module gains a single new public function
  (`get_admin_system_message`) and a single new public dataclass
  (`AdminSystemPrompt`). Both are added to `__all__`.

---

## Testing Plan

### Unit tests

`tests/test_settings_admin_prompt.py` (new):

- Returns `None` when `get_setting("system_prompt")` returns `None`.
- Returns `None` when the value is empty or whitespace-only.
- For a non-empty value: returns an `AdminSystemPrompt` whose
  `message.role == "system"`, whose text content begins with
  `<systeminstructions priority="highest">` and ends with
  `</systeminstructions>`, and whose `raw_text` is the stripped admin
  prompt **without** the wrapper.
- Trust-boundary check: a value containing `<script>alert(1)</script>`
  passes through unchanged in `raw_text` and inside the wrapper. (No
  sanitisation.)

### Handler-integration tests

For each of `_memory_extraction.py`, `_memory_consolidation.py`,
`_title_generation.py`, and `_vision_fallback.py`, two tests:

1. **Admin prompt set:** capture the `messages` list passed to
   `llm_stream_completion`. Assert the first message is `role="system"`
   and contains the wrapped admin prompt; assert the remaining messages
   match the existing structure.
2. **No admin prompt:** capture the `messages` list. Assert the structure
   is byte-identical to the pre-change baseline (no `system` message at
   the head).

For the three job handlers, additionally assert that
`check_and_reserve_budget` is invoked with a prompt-text argument that
includes the admin prompt's `raw_text` when set, and excludes it when not
set.

Tests follow the async-mock style of the existing
`tests/test_title_generation_handler.py`.

### Manual verification

After implementation, with a meaningful master prompt configured (e.g.
the project's standard NSFW-allowance preamble):

1. Trigger a memory extraction on a chat that previously got refused by
   an open-source model — confirm the extraction now succeeds.
2. Trigger title generation on the same chat — confirm the generated
   title is no longer a refusal string.
3. Upload an image to a chat using a non-vision-capable text model that
   triggers the fallback — confirm the description is produced.

---

## Out-of-Scope Follow-Ups

- **Compact and continue** is the next feature this unblocks. Designed
  separately.
- **Per-job admin-prompt overrides** (e.g. a different prompt for title
  generation than for chat) are not part of this change. If needed
  later, the helper can grow a `purpose: Literal["chat", "memory",
  "title", "vision"]` argument and the settings module can store
  per-purpose variants.
- **Caching** the admin prompt across calls is out of scope. The current
  read-per-call cost is negligible against the LLM call cost.
