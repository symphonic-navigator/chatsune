# ChatGPT Conversation Import — Design Spec

**Date:** 2026-05-11
**Status:** Draft, awaiting review
**Scope:** New backend module `chatgpt_import` + persona-detail UI tab to import ChatGPT
export bundles as native Chatsune sessions.

---

## 1. Context & Motivation

ChatGPT users can export their account data as a single `conversations.json` array — in
the wild, files up to ~105 MB containing hundreds of conversations. Among current
LLM providers, only ChatGPT has the user-base size and "I've moved on" inertia where
bulk migration to Chatsune is a realistic onboarding path; Claude and Grok do not have
the same migration pressure. Building a generic "importer plugin" framework would be
over-engineering for a single source.

The existing Chatsune memory-extraction pipeline (`backend/modules/memory/`) operates
on user/assistant turns of a Chatsune session — once a ChatGPT conversation is
materialised as a Chatsune session, the standard memory pipeline already covers
fact extraction. Therefore the architectural goal of this feature is to turn
ChatGPT conversations into **native Chatsune sessions** rather than feeding the
ChatGPT export through a parallel memory-only path.

---

## 2. Goals & Non-Goals

### Goals

- Accept ChatGPT `conversations.json` exports up to ~500 MB.
- Stream-parse the export without loading it fully into RAM.
- Persist parsed conversations server-side with a 14-day TTL; reset TTL on
  every import action.
- Let the user browse the parsed conversations from any persona-detail page,
  multi-select, and import the selected conversations as native sessions of
  *that* persona.
- Show per-conversation badges indicating which personas a conversation has
  already been imported into.
- Make imported sessions fully continuable in Chatsune (with a connection
  picker when the user first sends a follow-up).
- Surface progress and per-conversation outcomes via WebSocket events,
  consistent with existing Chatsune event-first conventions.

### Non-Goals

- No generic "importer plugin" framework. Only ChatGPT is supported.
- No import of attachments, images, tool-call outputs (Code Interpreter,
  Web Search, DALL-E). Users who need their original files have the
  Knowledge Base feature for that purpose.
- No client-side parsing of the 105 MB JSON. All parsing happens
  server-side.
- No automatic post-import memory extraction. Users trigger memory
  extraction manually from the memory page, as today.
- No re-import diff or "merge". A second import of the same conversation
  creates a second session (with a confirmation hint).

---

## 3. Architecture Overview

### 3.1 New backend module

`backend/modules/chatgpt_import/` — a standalone module with strict boundary
per the CLAUDE.md module-boundary rules.

```
backend/modules/chatgpt_import/
  __init__.py            ← exposes ChatGptImportService
  _handlers.py           ← REST endpoints
  _repository.py         ← MongoDB access (two collections)
  _parser.py             ← ijson streaming, tree-to-linear, filter rules
  _session_builder.py    ← ChatGPT conversation → Chatsune session shape
```

### 3.2 Public API surface

```python
class ChatGptImportService:
    async def upload(self, user_id: str, stream: AsyncIterator[bytes],
                     filename: str, file_size_hint: int | None) -> ImportId: ...

    async def get_active_import(self, user_id: str) -> ImportDto | None: ...

    async def list_conversations(self, user_id: str, import_id: str,
                                 persona_id: str,
                                 filters: ConversationFilters) -> list[ConversationItemDto]: ...

    async def import_conversations(self, user_id: str, import_id: str,
                                   persona_id: str,
                                   chatgpt_conversation_ids: list[str]) -> ImportBatchDto: ...

    async def delete_import(self, user_id: str, import_id: str) -> None: ...
```

### 3.3 Cross-module contacts

- `ChatService.create_imported_session()` — **new public API to be added to
  the `chat` module** as part of this work; required to materialise an
  imported conversation atomically with its messages. The `chatgpt_import`
  module never reaches into `chat`'s collections directly.
- `PersonaService.exists(persona_id)` (or equivalent existing API) — for
  persona-existence validation before queueing import jobs.

### 3.4 Job queue integration

Two new `JobType` values, dispatched through the existing Chatsune job
infrastructure:

- `JobType.CHATGPT_IMPORT_PARSE` — long-running (seconds to ~1 min for
  100 MB); streams, parses, persists per-conversation documents.
- `JobType.CHATGPT_IMPORT_CONVERSATION` — short (<1 s); reads one
  conversation document, calls `ChatService.create_imported_session()`,
  records the import in the conversation doc, resets parent TTL.

Both jobs emit WebSocket events through the existing event bus.

---

## 4. Data Model

### 4.1 Collection `chatgpt_imports` (parent)

One document per active user upload.

```python
{
    "_id": ObjectId,
    "user_id": str,
    "file_hash": str,                 # SHA-256, for re-upload detection
    "file_size_bytes": int,
    "uploaded_filename": str,
    "status": "parsing" | "ready" | "failed",
    "error_message": str | None,
    "conversation_count": int,        # filled when parsing completes
    "skipped_count": int,
    "skipped_reasons": dict[str, int],   # {"oversized": 1, "malformed": 2}
    "created_at": datetime,
    "expires_at": datetime,           # TTL field, 14 days from last activity
    "last_import_at": datetime | None,
}
```

MongoDB TTL index on `expires_at`. On every `import_conversations` call the
parent's `expires_at` is set to `now + 14 days` and `last_import_at` is
updated.

### 4.2 Collection `chatgpt_import_conversations`

One document per parsed conversation.

```python
{
    "_id": ObjectId,
    "import_id": ObjectId,            # reference to chatgpt_imports
    "user_id": str,                   # denormalised for query efficiency
    "chatgpt_conversation_id": str,   # original id from export
    "title": str,
    "create_time": datetime,
    "update_time": datetime,
    "default_model_slug": str | None, # e.g. "gpt-5", "gpt-4o", "gpt-4"
    "message_count": int,             # after filter
    "first_user_message_preview": str,        # ~200 chars
    "first_assistant_message_preview": str,   # ~200 chars
    "raw_data": dict,                 # ChatGPT conversation 1:1, for later import
    "imports": [                      # who imported this where
        {
            "persona_id": str,
            "session_id": str,
            "imported_at": datetime,
        }
    ],
    "expires_at": datetime,           # mirrors parent, updated together
}
```

Indexes:

- `(user_id, import_id, create_time desc)` — listing
- `(user_id, chatgpt_conversation_id)` — dedupe check
- `expires_at` — TTL

### 4.3 Sizing assumption

A single ChatGPT conversation realistically tops out at 2-3 MB, even with
heavy regeneration branches and metadata; theoretical max is bounded by
human typing/regeneration patterns, not by the context window. We therefore
embed `raw_data` directly and **do not implement a GridFS fallback**. If a
`BSONObjectTooLarge` error is ever raised on insert, we skip that one
conversation, record `skipped_reasons["oversized"]++`, and log it
structured. If oversize becomes a real pattern, GridFS is a follow-up.

### 4.4 Re-upload semantics

- Same `file_hash` already active for this user → return `409` with the
  existing `import_id`, no re-parse.
- Different `file_hash` already active → require explicit `replace=true`
  flag in the request body. With it, the old parent + all child docs are
  removed, then the new upload proceeds.

---

## 5. Parser

### 5.1 ChatGPT export format (observed)

Top-level: `[{...}, {...}, ...]` — array of conversation objects.

Conversation fields used:

- `title`, `create_time`, `update_time`
- `mapping` — `dict[node_id, NodeObj]` representing the message tree
- `current_node` — id of the active leaf
- `conversation_id` / `id` — UUID
- `default_model_slug`

Node structure:

```python
{"id": str, "message": MessageObj | None, "parent": str | None, "children": list[str]}
```

Root node has `message: None`, `parent: None`. Branches occur when the user
hit *regenerate* — the abandoned branch typically has `status: "in_progress"`
with `finish_details.type == "interrupted"`.

Content types seen in samples:

- `text` — `{"content_type": "text", "parts": [str, ...]}` — the standard.
- `user_editable_context` — `{"content_type": "user_editable_context",
  "user_profile": str, "user_instructions": str}` — Custom Instructions.
  Encoded as a `user`-role message with `metadata.is_user_system_message:
  true` and `metadata.is_visually_hidden_from_conversation: true`. The
  *raw* values are exposed under `metadata.user_context_message_data.
  about_user_message` and `about_model_message`; the top-level `user_profile`
  / `user_instructions` strings are wrapped with ChatGPT's reasoning
  preamble and should be ignored.

Defensive: any other `content_type` (`code`, `execution_output`,
`multimodal_text`, `tether_quote`, etc.) is skipped with a structured log
entry `chatgpt_import.unsupported_content_type` carrying the type name.

### 5.2 Tree-to-linear walk

```python
def linearise(mapping: dict, current_node_id: str) -> list[dict]:
    """Walk the parent chain from current_node back to root, then reverse."""
    chain: list[dict] = []
    visited: set[str] = set()
    node_id = current_node_id
    while node_id and node_id not in visited:
        visited.add(node_id)
        node = mapping.get(node_id)
        if not node:
            break
        if node["message"] is not None:
            chain.append(node["message"])
        node_id = node.get("parent")
    return list(reversed(chain))
```

Alternative branches are automatically discarded because they do not lie on
the path to `current_node`. The `visited` set guards against malformed
self-referential parents.

### 5.3 Filter rules

| Condition | Action |
|---|---|
| `author.role == "system"` | skip — these are always empty placeholder stubs |
| `metadata.is_visually_hidden_from_conversation == True` | skip — *unless* `content.content_type == "user_editable_context"` |
| `content.content_type == "user_editable_context"` | special-case into the synthetic first message (see 5.4) |
| `content.content_type == "text"` and all `parts` are empty | skip — pre-send empty assistant stubs |
| `content.content_type` not in `{"text", "user_editable_context"}` | skip + structured log |
| `author.role` not in `{"user", "assistant"}` | skip + structured log |
| `status != "finished_successfully"` (e.g. `"in_progress"` with `interrupted` finish) | skip — defence-in-depth alongside the current_node walk |

### 5.4 Custom Instructions mapping

When a `user_editable_context` message is encountered (typically at the
start of the chain), it becomes a single synthetic first user message:

```
[User Profile]
{metadata.user_context_message_data.about_user_message}

[Custom Instructions]
{metadata.user_context_message_data.about_model_message}
```

Timestamp: `conversation.create_time - 1 second`, so it strictly precedes
the first real user turn.

### 5.5 Message mapping to Chatsune shape

For each surviving message:

- `role`: 1:1 (`user` / `assistant`)
- `content`: `"\n".join(parts)` (`parts` is always a list; usually one
  string)
- `created_at`: `datetime.fromtimestamp(message.create_time, UTC)`; if
  `create_time` is `None`, fall back to `conversation.create_time`.
- `imported_model_slug` (optional, for UI): `metadata.model_slug`

### 5.6 Imported-session metadata

When materialising the Chatsune session:

- `created_at`: original `conversation.create_time` — preserves
  chronological sort order in the sessions list.
- `imported_at`: now — audit field.
- `title`: from the export.
- `imported_from`: `"chatgpt"`.
- `imported_model_slug`: `default_model_slug` or first assistant
  message's `model_slug`.
- `model_unique_id`: pseudo-slug `"imported:chatgpt:<original_slug>"`
  until the user picks a real connection on first follow-up send.

### 5.7 Preview generation at parse time

For each conversation, the parse job extracts and stores:

- `first_user_message_preview` — first ~200 chars of the first surviving
  user message (after filtering, excluding the Custom Instructions synthetic
  one).
- `first_assistant_message_preview` — first ~200 chars of the first
  surviving assistant message.
- `message_count` — count after all filters.

---

## 6. Backend API & Events

### 6.1 REST endpoints

All authenticated, scoped to `current_user`.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/chatgpt-import/uploads` | Multipart upload, streams to `/tmp`, starts parse job |
| `GET` | `/api/chatgpt-import/uploads/active` | Current active upload (or `null`) |
| `DELETE` | `/api/chatgpt-import/uploads/{import_id}` | Manual cleanup before TTL |
| `GET` | `/api/chatgpt-import/uploads/{import_id}/conversations` | List with filter/search/pagination, enriched per-persona status |
| `POST` | `/api/chatgpt-import/uploads/{import_id}/import` | Body: `{persona_id, chatgpt_conversation_ids: [...]}` — single or bulk, queues jobs |

Body for `POST /import`:

```json
{
  "persona_id": "abc123",
  "chatgpt_conversation_ids": ["68e8a65c-...", "caebbbff-..."]
}
```

Response:

```json
{
  "correlation_id": "imp-batch-xyz",
  "jobs": [
    {"chatgpt_conversation_id": "68e8a65c-...", "job_id": "job-1"},
    {"chatgpt_conversation_id": "caebbbff-...", "job_id": "job-2"}
  ]
}
```

### 6.2 Upload mechanics

To avoid pulling the entire file into memory:

1. Endpoint accepts `request: Request`, streams body chunks to
   `/tmp/chatgpt_import_{uuid}.json`.
2. SHA-256 is computed incrementally via `hashlib.sha256.update()` per
   chunk.
3. After the stream ends, a `chatgpt_imports` document is created with
   `status: "parsing"`, hash, size, filename.
4. `JobType.CHATGPT_IMPORT_PARSE` is dispatched with `file_path` and the
   response returns immediately.
5. The parse job opens the file and iterates with
   `ijson.items(file, "item")`, writing one `chatgpt_import_conversations`
   doc per array element. When complete, `status: "ready"` is set, the
   temp file is deleted.

### 6.3 New job types

```python
class JobType(StrEnum):
    # ... existing
    CHATGPT_IMPORT_PARSE = "chatgpt_import.parse"
    CHATGPT_IMPORT_CONVERSATION = "chatgpt_import.conversation"
```

### 6.4 New topics

In `shared/topics.py`:

```python
class Topics:
    # ... existing
    CHATGPT_IMPORT_PARSE_STARTED = "chatgpt_import.parse.started"
    CHATGPT_IMPORT_PARSE_PROGRESS = "chatgpt_import.parse.progress"
    CHATGPT_IMPORT_PARSE_DONE = "chatgpt_import.parse.done"
    CHATGPT_IMPORT_PARSE_FAILED = "chatgpt_import.parse.failed"
    CHATGPT_IMPORT_CONVERSATION_IMPORTED = "chatgpt_import.conversation.imported"
    CHATGPT_IMPORT_CONVERSATION_IMPORT_FAILED = "chatgpt_import.conversation.import_failed"
```

### 6.5 Event DTOs

In `shared/events/chatgpt_import.py`:

```python
class ChatGptImportParseStartedEvent(BaseModel):
    import_id: str
    filename: str
    file_size_bytes: int

class ChatGptImportParseProgressEvent(BaseModel):
    import_id: str
    conversations_indexed: int   # streaming; total only known at end

class ChatGptImportParseDoneEvent(BaseModel):
    import_id: str
    conversation_count: int
    expires_at: datetime
    skipped_count: int
    skipped_reasons: dict[str, int]

class ChatGptImportParseFailedEvent(BaseModel):
    import_id: str
    error_code: str
    error_message: str

class ChatGptImportConversationImportedEvent(BaseModel):
    import_id: str
    chatgpt_conversation_id: str
    persona_id: str
    session_id: str
    title: str

class ChatGptImportConversationImportFailedEvent(BaseModel):
    import_id: str
    chatgpt_conversation_id: str
    persona_id: str
    error_code: str
    error_message: str
```

### 6.6 Event scopes & correlation

- Parse events: scope `f"chatgpt_import:{import_id}"`.
- Conversation-imported events: published to both
  `f"chatgpt_import:{import_id}"` *and* `f"persona:{persona_id}"`, so the
  list view and any open persona detail pick up the change.
- Correlation: one `correlation_id` per upload (carried through all parse
  events); one `correlation_id` per `POST /import` call (carried through
  all per-conversation events of the batch).

### 6.7 Chat-module API addition

`backend/modules/chat` must expose:

```python
async def create_imported_session(
    self,
    *,
    persona_id: str,
    user_id: str,
    title: str,
    messages: list[ImportedMessageInput],
    imported_from: Literal["chatgpt"],
    imported_model_slug: str | None,
    original_created_at: datetime,
) -> SessionId: ...
```

The `ImportedMessageInput` DTO lives in `shared/dtos/chat.py`. Adding this
API is **part of this feature's scope**, not a follow-up.

### 6.8 Error responses

| Situation | Response |
|---|---|
| Upload file > 500 MB | 413 |
| Body is not JSON | 400 |
| JSON is not a top-level array | parse job fails the import doc; client polls/listens |
| Same `file_hash` already active | 409 with existing `import_id` |
| Different upload exists, no `replace=true` | 409 with `existing_import_id` |
| `persona_id` not found | 404 |
| `chatgpt_conversation_id` not in import | 404 |
| Conv-import job already running in same persona | 409 |
| Filter removes all messages | conversation-import job fails with code `no_convertible_messages` |
| Per-conv parse error | conversation skipped, counter incremented, other convs unaffected |
| > 50 % of convs failed parse | import marked `failed` overall |

---

## 7. UI Flow (Persona-Detail Tab)

### 7.1 Tab integration

New tab **"ChatGPT-Import"** on the persona detail page, alongside existing
tabs. Visual style follows the user-facing opulent prototype style (not
the catppuccin admin style).

### 7.2 State 1 — empty (no active upload)

Card with a primary `Upload file` button (no drag-and-drop). Explanatory
copy:

- "Upload your ChatGPT export (`conversations.json`). You can then import
  individual or multiple conversations into this persona as sessions."
- Bullet list: 14-day retention, TTL resets on import, file applies across
  all your personas.

### 7.3 State 2 — parse in progress

Sticky progress banner at the top of the tab:

```
[⏳]  File being processed — 47 conversations indexed …
```

The rest of the tab is disabled (greyed out, not hidden). On
`PARSE_FAILED`: red banner with `error_message` and a `Start another
upload` button.

### 7.4 State 3 — list view

Header strip: filename, conversation count, expires-at date, buttons
`Replace upload` and `Delete file`.

Filters row (all are dropdowns, not chips):

- Title search input (debounced)
- Sort: newest / oldest / title A-Z
- Status: all / not in this persona / not in any persona / in another persona

List rows, per row:

- Checkbox (multi-select)
- Title and a small mono-font model pill (e.g. `gpt-5`)
- Date and message count
- Inline preview: first user message and first assistant message, each
  truncated to ~200 chars, prefixed with `⟨user⟩` / `⟨assistant⟩`
  mono-font markers
- Status badges:
  - `in this persona, imported at …` — informational, re-import allowed
  - `in "Vale", imported at …` — informational, cross-persona
- Click on row (outside checkbox) → expand → full message list rendered
  with `⟨user⟩` / `⟨assistant⟩` line prefixes

Sticky bottom action bar when at least one row is selected:

```
N selected    [Import into this persona]   [×]
```

### 7.5 Import-confirmation modal

```
Confirm import
──────────────
Import 3 conversations into "Vale"?

• Hühnerbrust Geschnetzeltes Rezept
• Reversed Time and AdS
• Moon Darker Than Coal

2 of these were already imported into other personas — they will be
added to "Vale" as well.

[Cancel]   [Import]
```

Existing Chatsune modal primitive handles `--ui-scale` compensation; no
special positioning logic needed here.

### 7.6 During import

- Rows with an in-flight import job show a small spinner marker and are
  temporarily disabled.
- On `CONVERSATION_IMPORTED`: row badge updates live; toast at the bottom:
  "3 conversations imported. → Show sessions" linking to the persona's
  sessions list.
- On `CONVERSATION_IMPORT_FAILED`: per-row error strip with
  `error_message` and `Retry` button.

### 7.7 Replace-upload confirmation

```
Replace active file?
─────────────────────
There is still an active upload (conversations.json, 287 conversations).

If you upload a new one, the old list of not-yet-imported conversations
will be discarded.

Already-imported sessions remain untouched.

[Cancel]   [Replace]
```

On `Replace`: `DELETE /uploads/{id}` then `POST /uploads` with
`replace: true`.

### 7.8 Mobile layout (< 1024 px)

Single breakpoint at `lg`. On mobile:

- Compact row: title + date + model pill in line 1; message count + the
  first status badge in line 2.
- Inline preview collapsed by default with an expand affordance.
- Sticky bottom bar preserved (essential for multi-select on touch).
- Modal uses mobile full-height.

### 7.9 Front-end component tree

```
features/personas/chatgpt-import/
  ChatGptImportTab.tsx
  UploadEmptyState.tsx
  ParseProgressBanner.tsx
  ConversationList.tsx
    ConversationFilters.tsx
    ConversationRow.tsx
    ConversationPreviewExpanded.tsx
    MultiSelectActionBar.tsx
  ImportConfirmDialog.tsx
  ReplaceUploadDialog.tsx
  useChatGptImportEvents.ts

core/api/chatGptImportApi.ts
core/store/chatGptImportStore.ts
```

### 7.10 WebSocket subscription

`useChatGptImportEvents.ts` on mount subscribes to:

- `CHATGPT_IMPORT_PARSE_*` filtered by `chatgpt_import:{activeImportId}`
- `CHATGPT_IMPORT_CONVERSATION_*` filtered by both
  `chatgpt_import:{activeImportId}` *and*
  `persona:{currentPersonaId}`

Unsubscribes on unmount.

### 7.11 Continue chatting on an imported session

An imported session carries `model_unique_id =
"imported:chatgpt:<original_slug>"`. This pseudo-id is recognised by the
existing chat-send code path as non-sendable.

On the user's first `Send` in an imported session:

1. Chat input intercepts the send because of the `imported:` prefix.
2. A `ConnectionPickerDialog` is shown listing the user's available LLM
   connections (the same list used by the normal model-picker UI).
3. On selection, the session's `model_unique_id` is updated via the
   existing chat-module session-update API to the chosen real
   `{connection_id}:{model_slug}`.
4. The interrupted send is then dispatched normally.

After this one-time pick, the imported session behaves identically to any
native Chatsune session. The original ChatGPT model slug remains
accessible in the session metadata (`imported_model_slug`) for UI display
purposes but no longer participates in routing.

This dialog lives in the `chat` feature, not in `chatgpt-import` — it is
generic enough to handle any future "session created without a connection"
case. Implementing it is part of this feature's scope.

---

## 8. Error Handling & Edge Cases

Beyond the response codes in 6.8:

| Edge case | Behaviour |
|---|---|
| `current_node` references missing node | Conv skipped at parse, reason `"broken_current_node"` |
| Parent chain has a cycle | `visited` guard breaks the walk; conv skipped, reason `"malformed_tree"` |
| `BSONObjectTooLarge` on insert (>16 MB) | Conv skipped, reason `"oversized"`; logged. Other convs unaffected |
| Temp disk full during upload | 507; no doc created; temp file unlinked |
| Worker crash mid-parse or mid-import | Existing job-queue retry policy: 1 retry with backoff; on second failure, job marked `failed` and event published |
| User deletes persona while conv-import in flight | Job fails with code `persona_deleted`; event published |
| Two browser tabs trigger import of same conv into same persona simultaneously | Locked at the repository layer via atomic `findOneAndUpdate` on the conv's `imports` array; second job fails with 409 |
| WS disconnect during parse | Standard reconnect with catch-up from Redis Streams; UI resumes progress without action |
| Conversation has 0 messages after filtering | Conv-doc still created with `message_count: 0`; shown in list with a grey "No text messages" hint; multi-select skips it |
| Very large assistant message (>1 MB of text) | Accepted; Chatsune sessions have no hard message-size cap |

All skipped / failed events log structured fields: `correlation_id`,
`import_id`, `chatgpt_conversation_id`, `reason`. Consistent with the
Claude-oriented logging convention from CLAUDE.md.

---

## 9. Manual Verification

To be run on real hardware before merge. No "done" claim without these.

### Upload & parse

- [ ] Upload a real 105 MB export — progress banner appears, count climbs,
      completes cleanly.
- [ ] Re-upload the same file — 409 without re-parse; list visible
      immediately.
- [ ] Re-upload a different file — confirmation dialog; on accept, old list
      gone, new one in place.

### Parser correctness

- [ ] Import the "Hühnerbrust" conv — first message in the resulting
      Chatsune session is the synthetic Custom Instructions user message
      with `[User Profile]` + `[Custom Instructions]` (raw, no ChatGPT
      wrapper prose).
- [ ] Import the "Moon Darker Than Coal" conv — no `in_progress` /
      interrupted message appears in the Chatsune session (regenerate
      branch correctly discarded).
- [ ] Import a conv from your real export that contains a Code Interpreter
      / Web Search step — tool output absent from the session, no `[code]`
      junk tokens.

### UI

- [ ] List shows title, date, model pill, preview correctly.
- [ ] Title search filters.
- [ ] Sort dropdown changes order.
- [ ] Status dropdown filters badges.
- [ ] Multi-select 3 convs → Import button → confirm → WS events arrive
      per conv → badges update live.
- [ ] At `--ui-scale: 1.5`: modal centred correctly, sticky bottom bar
      does not drift.
- [ ] Mobile viewport (< 1024 px): layout works, multi-select usable.

### State & persistence

- [ ] Import 1 conv → close browser → return after 3 days: list still
      there, TTL has been pushed to "in 14 days".
- [ ] Leave a conv without any import for 14+ days → TTL cleans it up
      automatically.

### Multi-tab

- [ ] Open persona detail in two tabs → import in tab A → tab B sees the
      badge update live.

### Cross-persona

- [ ] Import a conv into persona A → open persona B → list shows badge
      `in "A", imported at …`.
- [ ] Re-import the same conv into B → confirm dialog mentions it; conv
      lands in B as well.
- [ ] In the sessions list of A and B: one new session each, with
      `created_at` matching the original ChatGPT date (not today).

### Continue chatting

- [ ] Open an imported session → pseudo-model `imported:chatgpt:gpt-5`
      visible in the selector.
- [ ] Write a reply → connection-picker dialog appears (because the
      pseudo-model is not sendable) → pick a real connection → send works,
      conversation continues.

### Memory extraction

- [ ] Trigger memory extraction manually on an imported session → job
      runs, journal entries appear.

---

## 10. Out-of-Scope / Future Work

The following are deliberately deferred:

- **Attachment / image import** — users with files use the Knowledge Base
  module.
- **Tool-call replay** — Code Interpreter / Web Search / DALL-E content
  cannot be replayed in Chatsune.
- **Bulk auto-memory-extraction over imported sessions** — sessions
  longer than the existing 20-message extraction window do not get
  retroactive full-conversation extraction. A future "extract over full
  session" option may relax this.
- **GridFS fallback for oversized conversations** — accept the skip for
  now; add only if telemetry shows real occurrences.
- **Importers for other providers** (Claude, Grok, Gemini) — not in
  scope; their user-bases do not have the same migration pressure.
- **Diff / merge on re-upload** — a second upload of a file containing
  the same conversation produces a fresh session if the user picks it;
  no smart deduplication.

---

## 11. Open Questions

None at spec-approval time. If something surfaces during implementation,
add it back here and surface it in the implementation plan.
