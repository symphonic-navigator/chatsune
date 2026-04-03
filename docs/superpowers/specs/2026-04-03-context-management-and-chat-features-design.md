# Context Management & Chat Features — Design Spec

**Goal:** Complete the inference pipeline with proper context window management,
token counting, system prompt assembly, and message edit/regenerate capabilities.

**Prerequisite check before implementation:** The system-wide system prompt
(`global_system_prompt` in `app_settings`) is being implemented in a parallel
session. Before starting implementation of the system prompt assembler, verify
that the settings infrastructure is in place and aligned with this spec.

---

## 1. System Prompt Assembly

### 1.1 Four-Layer Hierarchy

The system prompt is assembled from four sources, concatenated as XML-tagged
blocks with priority attributes. Each block is optional — if the source is
empty/null, the block is skipped entirely.

```xml
<systeminstructions priority="highest">
  [Admin global system prompt — from app_settings("global_system_prompt")]
</systeminstructions>

<modelinstructions priority="high">
  [Per-user, per-model system prompt addition — from user_model_configs]
</modelinstructions>

<you priority="normal">
  [Persona system prompt — from the session's persona]
</you>

<userinfo priority="low">
  What the user wants you to know about themselves:
  [User about_me field]
</userinfo>
```

A fifth layer (`<usermemory>`) is reserved for the future memory system
(see FOR_LATER.md). The XML tag name is reserved in the sanitiser now.

### 1.2 Data Sources

| Layer | Source | Module | Collection | Owner |
|-------|--------|--------|------------|-------|
| `systeminstructions` | `app_settings("global_system_prompt")` | settings | `app_settings` | Admin |
| `modelinstructions` | `UserModelConfig.system_prompt_addition` | llm | `user_model_configs` | User (per model) |
| `you` | `Persona.system_prompt` | persona | `personas` | User |
| `userinfo` | `User.about_me` | user | `users` | User |

### 1.3 Sanitiser

All user-controlled fields (model instructions, persona prompt, about me) are
sanitised before assembly. The admin global system prompt is trusted and NOT
sanitised.

**Sanitisation rules:** Strip all occurrences of reserved XML tags from
user-controlled content. This prevents prompt injection where a user embeds
`<systeminstructions>` inside their persona prompt to override admin guardrails.

**Reserved tags** (including hyphen/underscore variants):
- `systeminstructions`, `system-instructions`, `system_instructions`
- `modelinstructions`, `model-instructions`, `model_instructions`
- `you`
- `userinfo`, `user-info`, `user_info`
- `usermemory`, `user-memory`, `user_memory`

The sanitiser uses regex to strip both opening and closing tags with any
attributes, case-insensitively.

### 1.4 Assembly Preview

Two assembly modes:
- **`assemble()`** — Full XML output sent to the LLM. Includes all 4 layers.
- **`assemble_preview()`** — Human-readable version using `--- Heading ---`
  separators. Excludes the admin prompt (users should not see admin guardrails).
  Shown in the frontend system prompt preview UI.

### 1.5 Cache Prefix Implications

The system prompt is the first message in every request. All four sources are
stable within a session (admin settings rarely change, model config/persona/
about_me don't change mid-conversation). This means the system prompt tokens
are identical across requests in the same session, preserving the provider's
prompt cache prefix.

The system prompt is assembled fresh on each `handle_chat_send` call (not
cached between requests). Since the underlying data is stable, the token output
is identical — caching would add complexity for no benefit.

### 1.6 New Dependencies

**User module changes:**
- Add `about_me: str | None` field to the user document
- Add `PATCH /api/users/me/about-me` endpoint (body: `{ "about_me": "..." }`)
- Add public API: `get_user_about_me(user_id: str) -> str | None`

**Settings module changes:**
- Add public API: `get_setting(key: str) -> str | None`

**New shared code:**
- `backend/modules/chat/_prompt_assembler.py` — `assemble()` and `assemble_preview()`
- `backend/modules/chat/_prompt_sanitiser.py` — `sanitise(text: str) -> str`

---

## 2. Context Window Management

### 2.1 No Rolling Window

Unlike Prototype 2, Chatsune does **not** use a rolling window that silently
drops old messages. Instead, the context fills up and hits a hard block at 80%.

**Rationale:**
- Rolling window breaks the provider's prompt cache prefix (all tokens shift
  when leading messages are dropped)
- Users never know what the model has "forgotten" — silent data loss
- Explicit blocking + future synopsis feature is a better UX

### 2.2 Budget Calculation

```
systemPromptTokens  = tiktoken_count(assembled_system_prompt)
responseReserve     = 1000 + newUserMessageTokens
safetyReserve       = floor(maxContextTokens * 0.165)

availableForChat    = maxContextTokens - safetyReserve - systemPromptTokens - responseReserve
```

`maxContextTokens` is resolved from the provider model metadata (Redis cache).

**Prototype 2 bug not inherited:** The response reserve no longer double-counts
the new user message tokens. The new user message is counted once in
`responseReserve` and then appended to the completion messages after budget
selection.

### 2.3 Pair-Based Backread

Messages are grouped into pairs (user message + assistant reply). Selection
works from newest to oldest:

1. Load all messages for the session from MongoDB
2. Group into `(user, assistant)` pairs — incomplete trailing pairs are skipped
   during selection but the current user message is always included
3. Iterate from newest pair to oldest, accumulating token counts
4. Stop when the next pair would exceed `availableForChat`
5. Reverse selected pairs back to chronological order
6. Prepend system message, append new user message

**Pairs are never split.** A user message is always sent with its corresponding
assistant reply.

### 2.4 Cache Prefix Friendliness

Because there is no rolling window, the message prefix is stable within a
session:

```
Request 1: [system, pair1, pair2, user_msg]
Request 2: [system, pair1, pair2, pair3, user_msg]      → cache hit on prefix
Request 3: [system, pair1, pair2, pair3, pair4, user_msg] → cache hit grows
```

The prefix only breaks if the user edits/regenerates a message (which changes
the history) or if the session is resumed after an external change to the system
prompt sources. Both are acceptable — the user triggered the change.

### 2.5 Hard Block at 80%

When the context fill reaches 80% of `maxContextTokens`, the backend rejects
`chat.send` with a specific error event:

```python
ChatStreamErrorEvent(
    error_code="context_window_full",
    recoverable=False,
    user_message="Context window is full. Please start a new session.",
)
```

No inference attempt is made. The session state remains `idle`.

A future "Summarise & Continue" feature (FOR_LATER.md) will offer an elegant
alternative: LLM summarises the conversation, creates a new session with the
synopsis as a context prolog.

---

## 3. Token Counting

### 3.1 tiktoken with cl100k_base

Replace the current rough estimate (`len // 4`) with proper token counting
via the `tiktoken` library using the `cl100k_base` encoding.

**Why cl100k_base:** It is a pessimistic (over-counting) choice for most models,
which means we will never overflow the context window. This is a known trade-off
— accuracy per model would require model-specific tokenisers, which adds
complexity for marginal benefit.

### 3.2 Token Count Caching

- Each message's `token_count` is computed via tiktoken at save time and stored
  in the MongoDB document (field already exists)
- The system prompt tokens are counted fresh on each request (content is
  session-stable, so the count is always the same, but caching adds complexity
  for no benefit)
- The `tiktoken` encoding is loaded once at module level (it is thread-safe
  and reusable)

### 3.3 Dependency

Add `tiktoken` to `backend/pyproject.toml` dependencies.

---

## 4. Context Ampel (Traffic Light)

### 4.1 Thresholds

| Status | Threshold (% of total `maxContextTokens`) | Meaning |
|--------|---------------------------------------------|---------|
| Green  | 0–50%                                       | Plenty of space |
| Yellow | 50–65%                                      | Getting full |
| Orange | 65–80%                                      | Should wrap up soon |
| Red    | >= 80%                                       | Blocked — no more messages accepted |

### 4.2 Delivery

The ampel status is included in every `ChatStreamEndedEvent`:

```python
class ChatStreamEndedEvent(BaseModel):
    # ... existing fields ...
    context_status: Literal["green", "yellow", "orange", "red"]
    context_fill_percentage: float  # 0.0–1.0, for precise UI display
```

The `context_fill_percentage` field is new — it allows the frontend to show a
progress bar or percentage alongside the colour indicator.

### 4.3 Pre-Send Check

Before starting inference, `handle_chat_send` checks the context fill. If
the projected fill (current messages + new user message + response reserve)
would exceed 80%, the request is rejected with `context_window_full` error
immediately — no inference is started, no tokens are wasted.

---

## 5. Message Edit

### 5.1 WebSocket Message

```json
{
    "type": "chat.edit",
    "session_id": "...",
    "message_id": "...",
    "content": [{ "type": "text", "text": "edited content" }]
}
```

### 5.2 Flow

1. Validate: message exists, belongs to user, role is `user`, session is `idle`
2. Delete all messages with `created_at` after the target message
3. Overwrite the target message content and recalculate `token_count`
4. Emit `chat.messages.truncated` event (session_id, after_message_id)
5. Emit `chat.message.updated` event (full updated message)
6. Start inference automatically (same path as `chat.send`)

### 5.3 Events

```python
class ChatMessagesTruncatedEvent(BaseModel):
    type: str = "chat.messages.truncated"
    session_id: str
    after_message_id: str  # everything after this message was deleted
    correlation_id: str
    timestamp: datetime

class ChatMessageUpdatedEvent(BaseModel):
    type: str = "chat.message.updated"
    session_id: str
    message_id: str
    content: str
    token_count: int
    correlation_id: str
    timestamp: datetime
```

---

## 6. Message Regenerate

### 6.1 WebSocket Message

```json
{
    "type": "chat.regenerate",
    "session_id": "..."
}
```

### 6.2 Flow

1. Validate: session belongs to user, session is `idle`
2. Find the last message — must be role `assistant`
3. Delete it
4. Emit `chat.message.deleted` event (session_id, message_id)
5. Start inference using the existing last user message

### 6.3 Event

```python
class ChatMessageDeletedEvent(BaseModel):
    type: str = "chat.message.deleted"
    session_id: str
    message_id: str
    correlation_id: str
    timestamp: datetime
```

---

## 7. Shared Code Between Edit, Regenerate, and Send

All three flows converge on the same inference path. The differences are only
in message preparation:

| Flow | Message Prep | Then |
|------|-------------|------|
| `chat.send` | Save new user message | Run inference |
| `chat.edit` | Truncate + update existing message | Run inference |
| `chat.regenerate` | Delete last assistant message | Run inference |

The existing `handle_chat_send` will be refactored: the inference-triggering
logic (system prompt assembly, context building, InferenceRunner invocation)
is extracted into a shared `_run_inference(session_id, user_id)` function.
The three WebSocket handlers each do their specific message prep, then call
`_run_inference`.

---

## 8. File Map

### New Files

| File | Responsibility |
|------|---------------|
| `backend/modules/chat/_prompt_assembler.py` | `assemble()` and `assemble_preview()` |
| `backend/modules/chat/_prompt_sanitiser.py` | Strip reserved XML tags from user content |
| `backend/modules/chat/_context.py` | Context window selection, budget calculation, ampel |
| `backend/modules/chat/_token_counter.py` | tiktoken wrapper, module-level encoding singleton |
| `FOR_LATER.md` | Deferred features with rationale |

### Modified Files

| File | Change |
|------|--------|
| `backend/modules/chat/__init__.py` | Refactor: extract `_run_inference`, add `handle_chat_edit`, `handle_chat_regenerate` |
| `backend/modules/chat/_repository.py` | Add `delete_messages_after()`, `update_message_content()`, `get_last_message()` |
| `backend/modules/user/__init__.py` | Expose `get_user_about_me()` |
| `backend/modules/user/_repository.py` | Add `about_me` field support, `update_about_me()` |
| `backend/modules/user/_handlers.py` | Add `PATCH /api/users/me/about-me` |
| `backend/modules/settings/__init__.py` | Expose `get_setting()` |
| `backend/ws/router.py` | Add `chat.edit` and `chat.regenerate` dispatch |
| `backend/ws/event_bus.py` | Add fan-out rules for new chat events |
| `shared/events/chat.py` | Add truncated/updated/deleted events |
| `shared/topics.py` | Add new topic constants |
| `shared/dtos/chat.py` | Add `context_fill_percentage` to relevant DTOs |
| `backend/pyproject.toml` | Add `tiktoken` dependency |

---

## 9. Summary of Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Rolling window | No | Breaks cache prefix, silent data loss |
| Hard block threshold | 80% of total context | Conservative, preserves cache, clear UX |
| Token counting | tiktoken cl100k_base | Pessimistic but safe, proven approach |
| System prompt | 4-layer XML with sanitiser | Security + model clarity + cache stability |
| Message edit | Linear truncation | Simple, no branching complexity |
| Regenerate | Delete + re-infer | Proven pattern from Prototype 2 |
| Memory layer | Deferred (FOR_LATER) | Tools replace RAG, memory not needed yet |
| Synopsis & continue | Deferred (FOR_LATER) | Differentiating feature, needs own design |
