# Memory System — Design Spec

This document is the authoritative design for Chatsune's per-persona memory system.
It supersedes MEMORY-SYSTEM.md (the brainstorming document) on all points where they differ.

---

## Overview

A semi-automatic, per-persona memory pipeline that extracts facts from user messages,
stages them for optional review, and consolidates them into a structured long-term
memory body. Memory is injected into the system prompt at session start.

**Core principles:**
- Memory is always per persona. No cross-persona memory layer. The user's `about_me`
  profile field covers universal facts.
- Each persona learns about the user independently.
- The system is opt-out: entries auto-commit after 48h. Users who want control can
  review; users who don't care get automatic memory.
- Dreaming (consolidation) is the quality gate, not user review.
- Incognito sessions are completely excluded — no extraction, no journal entries.

---

## Module Structure

Memory lives in its own module, not inside persona.

```
backend/modules/memory/
  __init__.py              -- Public API: router, init_indexes(), get_memory_context()
  _repository.py           -- MongoDB ops: journal entries + memory bodies
  _handlers.py             -- REST endpoints for the memory page
  _extraction.py           -- Journal extraction job handler
  _consolidation.py        -- Dreaming job handler
  _assembly.py             -- RAG assembly for prompt injection
  _parser.py               -- Tolerant JSON parser for extraction output
```

**Public API surface:**
- `router` — FastAPI router for memory page endpoints
- `init_indexes()` — called at startup
- `get_memory_context(user_id, persona_id) -> str | None` — returns assembled XML
  block for prompt injection, or None if no memory exists

---

## Data Model

### Collection: `memory_journal_entries`

```python
{
    "_id": ObjectId,
    "user_id": str,
    "persona_id": str,
    "content": str,                    # full text of the entry
    "category": str | None,            # optional, LLM-suggested
    "source_session_id": str,          # which session it was extracted from
    "state": str,                      # "uncommitted" | "committed" | "archived"
    "is_correction": bool,             # contradicts existing memory
    "archived_by_dream_id": str | None,
    "created_at": datetime,
    "committed_at": datetime | None,
    "auto_committed": bool,
}
```

**Indexes:**
- Compound: `(user_id, persona_id, state)` + `created_at` sorted
- Used for: listing entries by state, auto-commit queries, extraction input

### Collection: `memory_bodies`

```python
{
    "_id": ObjectId,
    "user_id": str,
    "persona_id": str,
    "content": str,                    # consolidated memory body text
    "token_count": int,
    "version": int,                    # monotonically increasing
    "entries_processed": int,          # how many journal entries were consumed
    "created_at": datetime,
}
```

**Indexes:**
- Compound: `(user_id, persona_id, version)` descending, unique
- Used for: fetching current version, version history, rollback

### Limits

| Parameter                 | Default | Notes                                     |
|---------------------------|---------|-------------------------------------------|
| Max uncommitted entries   | 50      | Oldest discarded with warning event       |
| Auto-commit timeout       | 48h     | Configurable per user later               |
| Memory body max tokens    | 3000    | Per persona                               |
| Versions retained         | 5       | For rollback                              |
| RAG budget max tokens     | 6000    | Via `MEMORY_RAG_MAX_TOKENS` in `.env`     |
| Soft limit (entries)      | 10      | Triggers 6h auto-dream                    |
| Hard limit (entries)      | 25      | Triggers immediate dream                  |
| Dream cooldown            | 6h      | Minimum between auto-dreams               |

---

## Stage 1: Journal Extraction

### Trigger Conditions

| Trigger            | Condition                                                        |
|--------------------|------------------------------------------------------------------|
| Idle               | 5 min after last user message in a session with this persona     |
| Session close      | Session explicitly closed or WebSocket timeout                   |
| Periodic fallback  | Every 15 min if neither idle nor close fired                     |
| Manual             | User clicks "Extract Now" button (see conditions below)         |

All triggers submit a job via the existing job system (Redis Streams, per-user lock).
If the user is chatting, the job waits — slightly longer TTFT is accepted.

### Manual Trigger Button

Appears in the journal dropdown when **both** conditions are met:
- 30 minutes since last extraction for this persona
- At least 5 user messages since last extraction

No toast, no push notification — only the button becomes visible in the dropdown.

Backend tracks `last_extraction_at` and `messages_since_extraction` per (user_id, persona_id)
in Redis (lightweight, no MongoDB needed).

### Extraction Prompt Input

1. **Existing memory body** — for duplicate/contradiction detection
2. **Existing journal entries** (committed + uncommitted) — to avoid duplicating pending entries
3. **New user messages** since last extraction

### Content Filtering

Before sending messages to the extraction LLM, strip technical/domain-specific raw data:
- Code blocks (fenced and indented)
- Stack traces, log output
- JSON/YAML/XML dumps
- CLI output, configuration file contents

**Keep the human context around it.** "I'm working on a Redis caching problem" is extracted;
the pasted log output is not. This rule is domain-agnostic — applies whether the user
discusses software, construction, medicine, or anything else.

The extraction prompt reinforces this: "Do not extract pasted technical content, but note
what the user discusses, their opinions, preferences, and the context of their work."

### Extraction Output Format

JSON array with tolerant parsing:

```json
[
  {"content": "Prefers dark UI themes", "category": "preference", "is_correction": false},
  {"content": "Name is Chris (corrects earlier 'Christian')", "category": "fact", "is_correction": true}
]
```

**Tolerant parser (`_parser.py`):**
- Strips markdown code fences (```json ... ```)
- Repairs trailing commas
- Attempts `json.loads` first
- Falls back to regex-based extraction of individual JSON objects
- Timestamps set by backend (based on newest source message), not by LLM

### Incognito Exclusion

Sessions with incognito flag are completely skipped. No extraction, no journal entries.

---

## Stage 2: Uncommitted Journal Entries

### Lifecycle

```
Extraction creates entry (state: "uncommitted")
    |
    +-- User commits manually --> state: "committed"
    +-- User edits           --> content updated, stays "uncommitted"
    +-- User deletes          --> hard delete
    +-- 48h elapsed           --> state: "committed", auto_committed: true
```

### Auto-Commit

- Runs as a periodic cleanup loop (every 10 min) in `main.py`, same pattern as
  existing session cleanup
- Finds all uncommitted entries with `created_at < now - 48h`
- Sets `state: "committed"`, `committed_at: now`, `auto_committed: true`
- Publishes `MEMORY_ENTRY_AUTO_COMMITTED` event per entry (batched under one correlation_id)

### 50-Entry Cap

When a new extraction would push uncommitted entries past 50, the oldest uncommitted
entries are discarded (hard delete) to make room. Publishes a warning event to the user:
"X oldest journal entries for [Persona] were discarded — please review more often."

### Toast Notification (Every 50 Uncommitted)

- Counter per persona, tracks current uncommitted entry count
- Resets to 0 on any user action (commit or delete) on an uncommitted entry of that persona
- At multiples of 50 (50, 100, 150...): toast with link to memory page
- Toast text: "[Persona] has 50 unreviewed memories — review now?"

---

## Stage 3: Committed Entries & Dreaming

### Dreaming Triggers

| Trigger    | Condition                                    | Behaviour        |
|------------|----------------------------------------------|------------------|
| Hard limit | >= 25 committed entries                      | Immediate        |
| Soft limit | >= 10 committed entries AND 6h since last dream | Automatic     |
| Manual     | User clicks "Dream Now" on memory page       | Immediate        |

**Cooldown:** 6h minimum between automatic dreams. Manual trigger ignores cooldown.

### Consolidation Process

1. Load current memory body + all committed journal entries
2. Send to the persona's LLM with consolidation prompt
3. LLM produces a new memory body (free structure — LLM decides organisation)
4. Validate: not empty, within 3000-token limit, parseable text
5. Store new memory body version, archive processed entries
   (`state: "archived"`, `archived_by_dream_id: dream_id`)
6. Publish `MEMORY_DREAM_COMPLETED` event

### Consolidation Prompt Instructions

- Integrate new journal entries into the existing memory body
- Corrections (`is_correction: true`) override older information
- When approaching the token limit: prioritise newer and more important information
- Summarise rather than delete — compress information density, don't discard
- Free structure, but group logically (the LLM decides how)

### Versioning & Rollback

- Last 5 versions of the memory body are retained
- Older versions are deleted when a new version is stored
- User can view previous versions on the memory page and rollback
- Rollback creates a new version (copies old content) — no destructive overwrite
- Publishes `MEMORY_BODY_ROLLBACK` event

### Error Handling

- If dreaming fails (LLM error, validation failure): committed entries stay committed,
  nothing is archived
- Publishes `MEMORY_DREAM_FAILED` event — error toast shown to user
- Retries at next trigger point

---

## Stage 4: RAG Assembly & Prompt Injection

### Injection Timing

Session start or restart only. No mid-session updates (would invalidate KV cache prefix).

### Assembly Algorithm

```
remaining = MEMORY_RAG_MAX_TOKENS (default 6000)

1. Memory body (always included in full)
   remaining -= memory_body_tokens

2. Committed entries (newest first)
   for each entry:
     if entry_tokens <= remaining: inject, remaining -= entry_tokens

3. Uncommitted entries (newest first)
   for each entry:
     if entry_tokens <= remaining: inject, remaining -= entry_tokens
```

### System Prompt Integration

Uses the already-reserved `<usermemory>` tag in the prompt assembler:

```xml
<systeminstructions priority="highest">...</systeminstructions>
<modelinstructions priority="high">...</modelinstructions>
<you priority="normal">...</you>
<usermemory priority="normal">
  <memory-body>
    ...consolidated long-term memory...
  </memory-body>
  <journal>
    ...recent journal entries (committed, then uncommitted, newest first)...
  </journal>
</usermemory>
<userinfo priority="low">...</userinfo>
```

**No memory exists:** The `<usermemory>` block is omitted entirely — no empty tag.

**Integration point:** The prompt assembler calls `memory.get_memory_context(user_id, persona_id)`
which returns the fully assembled XML string or None. The memory module owns the XML
construction and token budget enforcement.

---

## Events

### Topics (added to `shared/topics.py`)

```
MEMORY_EXTRACTION_STARTED
MEMORY_EXTRACTION_COMPLETED
MEMORY_EXTRACTION_FAILED
MEMORY_ENTRY_CREATED
MEMORY_ENTRY_COMMITTED
MEMORY_ENTRY_UPDATED
MEMORY_ENTRY_DELETED
MEMORY_ENTRY_AUTO_COMMITTED
MEMORY_DREAM_STARTED
MEMORY_DREAM_COMPLETED
MEMORY_DREAM_FAILED
MEMORY_BODY_ROLLBACK
```

### Event Scope

All memory events use `scope: "persona:{persona_id}"`.

### Shared DTOs (`shared/dtos/memory.py`)

```python
class JournalEntryDto(BaseModel):
    id: str
    persona_id: str
    content: str
    category: str | None
    state: str
    is_correction: bool
    created_at: datetime
    committed_at: datetime | None
    auto_committed: bool

class MemoryBodyDto(BaseModel):
    persona_id: str
    content: str
    token_count: int
    version: int
    created_at: datetime

class MemoryBodyVersionDto(BaseModel):
    version: int
    token_count: int
    entries_processed: int
    created_at: datetime
    # content omitted — loaded individually on demand

class MemoryContextDto(BaseModel):
    persona_id: str
    uncommitted_count: int
    committed_count: int
    last_extraction_at: datetime | None
    last_dream_at: datetime | None
    can_trigger_extraction: bool   # 30min + 5msg condition met
```

### Shared Events (`shared/events/memory.py`)

Each event wraps the relevant DTO(s) in its payload. Follows the existing
`BaseEvent` pattern with `type`, `scope`, `correlation_id`, `timestamp`.

### Frontend Notifications

| Event                           | UI Reaction                                                       |
|---------------------------------|-------------------------------------------------------------------|
| `ENTRY_CREATED`                 | Badge count up, badge blinks (2-3 pulses)                        |
| `ENTRY_COMMITTED`               | Badge count down, toast counter reset                            |
| `ENTRY_UPDATED`                 | Update entry in dropdown/memory page                             |
| `ENTRY_DELETED`                 | Badge count down, toast counter reset                            |
| `ENTRY_AUTO_COMMITTED`          | Badge count down, small toast: "X entries auto-committed"        |
| `DREAM_STARTED`                 | Spinner on memory page                                           |
| `DREAM_COMPLETED`               | Toast: "[Persona] dreamed — N memories processed", refresh page  |
| `DREAM_FAILED`                  | Error toast: "Dreaming failed for [Persona]"                     |
| `BODY_ROLLBACK`                 | Toast: "Memory rolled back to version N"                         |
| Uncommitted hits 50-multiple    | Toast: "[Persona] has N unreviewed memories — review now?" + link|

---

## Frontend

### Journal Dropdown (Chat Header)

- Badge button next to persona name with counter
- Badge colour based on uncommitted count:
  - 0: no badge shown
  - 1-20: green
  - 21-35: yellow
  - 36+: red
- Badge blinks briefly on new entries (CSS animation, 2-3 pulses then stops)
- Click opens dropdown panel:
  - Full text of each uncommitted entry
  - Timestamp per entry
  - Quick actions per entry: Commit, Delete
  - "Extract Now" button — only visible when 30min + 5msg condition is met
  - "Open Memory Page" link at the bottom

### Memory Page (per persona)

Accessible via: journal dropdown link, persona overview, toast links.

(!) indicator in navigation when uncommitted entries exist for any persona.

**Section 1: Uncommitted Entries**
- Full list with complete text, timestamp, category tag
- Single actions: Commit, Edit, Delete
- Select-multiple with checkboxes: Commit Selected, Delete Selected
- "Commit All" shortcut button
- Auto-commit countdown hint per entry: "Auto-commit in Xh"

**Section 2: Committed Entries**
- Full list with complete text, timestamp
- Actions: Edit, Delete
- Count display: "N entries waiting for next dream"

**Section 3: Memory Body**
- Current consolidated text (full content, read-only)
- Token counter: "1847 / 3000 tokens"
- Version history: dropdown or list of last 5 versions
- Select version to view content, "Rollback" button
- "Dream Now" button with spinner while dreaming runs

---

## Resolved Design Decisions

These were open questions in the brainstorming document. All are now resolved:

| Question | Decision | Rationale |
|----------|----------|-----------|
| Cross-persona memory | None — `about_me` is sufficient | Each persona learns independently; simplest, most privacy-respecting |
| Memory body structure | Free-form, LLM decides | Start simple, add structure constraints later if needed |
| Extraction output format | JSON with tolerant parser | Not all models support structured output; tolerant parser handles weak models |
| Lock granularity | Per user | Upstream provider concurrency limits require it |
| Old uncommitted entries | Auto-commit after 48h, 50-cap | Dreaming is the quality gate, not user review; auto-commit prevents data loss |
| Module location | Own module `backend/modules/memory/` | Complex enough for own boundaries; accesses persona via public API |
