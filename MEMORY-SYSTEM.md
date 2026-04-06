# Memory System Design

This document describes the design for Chatsune's per-persona memory system.
It covers the data pipeline, RAG assembly, consolidation ("dreaming"), and
open questions that need resolution before implementation.

---

## Core Principle

Memory is always **per persona**. Each persona maintains its own memories about
the user. There is no shared memory layer across personas (see Open Questions).

The system is **semi-automatic**: raw data flows through a staged pipeline from
extraction to consolidation, with optional human review at each stage.

---

## Data Pipeline

```
User messages
    │
    ▼
┌─────────────────────────┐
│  Journal Extraction     │  Background job, LLM-based
│  (every 15 min idle     │  Produces timestamped entries
│   or on session close)  │
└────────┬────────────────┘
         ▼
┌─────────────────────────┐
│  Uncommitted Journal    │  User can: review, edit, delete
│  Entries                │  Auto-commits after 48h
└────────┬────────────────┘
         ▼
┌─────────────────────────┐
│  Committed Journal      │  Verified facts, ready for
│  Entries                │  consolidation
└────────┬────────────────┘
         ▼
┌─────────────────────────┐
│  Dreaming               │  LLM-based consolidation
│  (Consolidation)        │  Merges entries into body
└────────┬────────────────┘
         ▼
┌─────────────────────────┐
│  Memory Body            │  Structured long-term memory
│  (max 3000 tokens)      │  Injected at session start
└─────────────────────────┘
```

---

## Stage 1: Journal Extraction

A background job extracts new journal entries from user messages. It runs
the same LLM model that the persona uses for chat.

### Trigger Conditions

- **Idle trigger:** 5 minutes after the last user message in any session with
  that persona (avoids blocking active chat — see Per-User Lock below)
- **Session close trigger:** when a chat session is explicitly closed or times
  out (WebSocket disconnect + timeout, not just disconnect alone)
- **Periodic fallback:** every 15 minutes if neither of the above fired

### Extraction Prompt

The LLM receives:

1. **Existing memory body** — to avoid duplicating already-consolidated knowledge
   and to detect contradictions (newer information should override)
2. **Existing journal entries** (committed + uncommitted) — to avoid duplicating
   pending entries; contradictions here also generate new entries
3. **New user messages** — the raw material to extract from

The prompt instructs the LLM to:

- Extract facts, preferences, relationships, and personal information
- Note technologies, projects, and domains the user discusses, but not code itself
- Produce structured output (JSON array of entries, not free text)
- Timestamp each entry based on the source message (use the latest message
  timestamp when multiple messages contribute to one insight)
- Perform **semantic** de-duplication — text comparison is insufficient
- Flag contradictions with existing memory/journal as explicit correction entries

### Multipart Content

- **Text attachments:** include in extraction (may contain personal information)
- **Images:** skip for now (would require vision model)
- **Code blocks:** the extraction prompt says: "Do not extract code snippets,
  but note what technologies, projects, or domains the user discusses."

---

## Stage 2: Uncommitted Journal Entries

Extracted entries land here for optional user review.

### User Actions

- **Review and commit** — entry moves to committed state
- **Edit** — correct errors before committing
- **Delete** — discard unwanted entries

### Auto-Commit

Uncommitted entries are **automatically committed after 48 hours** unless the
user deletes them. A banner in the UI warns: "X entries will auto-commit in
Y hours — review now?"

This makes the system **opt-out rather than opt-in**, reducing cognitive load.
Users who want control can review; users who do not care get automatic memory.

### Limits

| Parameter                  | Default | Notes                              |
|----------------------------|---------|------------------------------------|
| Max uncommitted entries    | 50      | Oldest discarded with warning      |
| Auto-commit timeout        | 48h     | Configurable per user (later)      |

### Frontend Visibility

- **Chat header:** badge showing uncommitted entry count, clickable to persona
  memory page
- **Persona overview page:** uncommitted entry count
- **Persona memory page:** full list with review/edit/delete/commit actions

---

## Stage 3: Committed Journal Entries

Verified entries waiting for consolidation into the memory body.

### Dreaming Triggers

Consolidation ("dreaming") is triggered by:

| Trigger       | Condition                                      | Behaviour          |
|---------------|------------------------------------------------|--------------------|
| **Hard limit** | >= 25 committed entries                        | Immediate trigger  |
| **Soft limit** | >= 10 committed entries AND 6h since last dream | Periodic trigger   |
| **Manual**     | User clicks "Dream now"                        | Immediate trigger  |

When the soft limit is reached, the user sees a suggestion: "Your persona has
N pending memories — trigger a dream?" This is informational; the system will
auto-dream at the 6h mark regardless.

### After Dreaming

Committed entries that were processed are **archived** (not deleted). They are
marked with the dream's timestamp and version number. This allows the user to
trace what was consolidated and when.

---

## Stage 4: Dreaming (Consolidation)

The LLM merges committed journal entries into the existing memory body.

### Process

1. Load current memory body + all committed journal entries
2. Send to the persona's LLM with consolidation prompt
3. LLM produces a new memory body that integrates the journal entries
4. Validate: not empty, within token limit, parseable
5. Store new memory body version, archive processed entries
6. Publish event to frontend (toast: "Persona X dreamed — N entries processed")

### Memory Body Constraints

- **Maximum size:** 3000 tokens
- **Structure:** the consolidation prompt should produce structured sections
  (e.g. facts, preferences, relationships, events) rather than free-form prose.
  This helps with prioritisation when the body approaches the limit and
  prepares for future tool-based retrieval.
- **Overflow handling:** the consolidation prompt must instruct the LLM to
  prioritise and summarise when approaching the limit — newer and more
  important information takes precedence over older, less significant details.

### Memory Body Versioning

The last **5 versions** of the memory body are retained. The user can view
previous versions and rollback if a dream produced a bad result.

| Parameter                  | Default | Notes                              |
|----------------------------|---------|------------------------------------|
| Memory body max tokens     | 3000    | Per persona                        |
| Versions retained          | 5       | For rollback                       |
| Soft limit (entries)       | 10      | Triggers suggestion + 6h auto-dream|
| Hard limit (entries)       | 25      | Triggers immediate dream           |
| Dream cooldown             | 6h      | Minimum time between auto-dreams   |

---

## RAG Assembly (Injection)

Memory is injected into the system prompt **at session start or restart only**.
It is not updated mid-session to avoid invalidating the KV cache prefix and
increasing cost.

### Assembly Order and Priority

The memory RAG budget is filled in strict priority order:

1. **Memory body** (highest priority) — always included in full
2. **Committed journal entries** — filled newest-first until budget exhausted
3. **Uncommitted journal entries** — filled newest-first with remaining budget

### Token Budget

| Parameter                  | Default | Source       |
|----------------------------|---------|--------------|
| `MEMORY_RAG_MAX_TOKENS`    | 6000    | `.env`       |

The total injected memory must not exceed this budget. The assembly algorithm:

```
remaining = MEMORY_RAG_MAX_TOKENS

1. Inject memory body (always)
   remaining -= memory_body_tokens

2. For each committed entry (newest first):
   if entry_tokens <= remaining:
     inject entry
     remaining -= entry_tokens

3. For each uncommitted entry (newest first):
   if entry_tokens <= remaining:
     inject entry
     remaining -= entry_tokens
```

### System Prompt Layer

Memory is injected as a dedicated XML layer in the system prompt, between the
persona layer and the user-info layer:

```xml
<systeminstructions priority="highest">...</systeminstructions>
<modelinstructions priority="high">...</modelinstructions>
<you priority="normal">...</you>
<usermemory priority="normal">
  <memory-body>
    ...consolidated long-term memory...
  </memory-body>
  <journal>
    ...recent journal entries not yet consolidated...
  </journal>
</usermemory>
<userinfo priority="low">...</userinfo>
```

The `<usermemory>` tag is already reserved and sanitised against user injection
(see `_prompt_sanitiser.py`).

---

## Per-User Lock Problem

The existing job system uses per-user asyncio locks to prevent concurrent LLM
calls. This means a journal extraction or dreaming job **would block chat
inference** for that user.

### Mitigation Strategy

Options (to be decided during implementation):

1. **Idle-based triggering** — only extract when the user has been idle for 5+
   minutes, making collisions unlikely
2. **Priority queue** — chat inference always takes priority; background jobs
   yield and retry after the chat completes
3. **Lock granularity** — separate locks per persona or per job-type, allowing
   extraction for persona A while chatting with persona B

Option 1 is the simplest and may be sufficient. Options 2 and 3 are fallbacks
if real-world usage shows collisions.

---

## Events

All memory operations publish events through the standard event bus.

### Topics (to be added to `shared/topics.py`)

```
MEMORY_EXTRACTION_STARTED
MEMORY_EXTRACTION_COMPLETED
MEMORY_EXTRACTION_FAILED
MEMORY_ENTRY_CREATED          (new uncommitted entry)
MEMORY_ENTRY_COMMITTED
MEMORY_ENTRY_UPDATED          (user edit)
MEMORY_ENTRY_DELETED
MEMORY_ENTRY_AUTO_COMMITTED
MEMORY_DREAM_STARTED
MEMORY_DREAM_COMPLETED        (payload: entries_processed count)
MEMORY_DREAM_FAILED
MEMORY_BODY_ROLLBACK
```

### Frontend Notifications

| Event                       | UI Element                                    |
|-----------------------------|-----------------------------------------------|
| `ENTRY_CREATED`             | Badge count update in chat header + overview  |
| `ENTRY_AUTO_COMMITTED`      | Toast: "X entries auto-committed for [persona]"|
| `DREAM_COMPLETED`           | Toast: "Persona [name] dreamed — N entries processed" |
| `DREAM_FAILED`              | Toast (error): "Dream failed for [persona]"   |
| `BODY_ROLLBACK`             | Toast: "Memory rolled back to version N"      |

---

## Module Boundaries

Memory lives in the **persona module** (`backend/modules/persona/`) since memory
is a persona concern. It does not get its own top-level module.

Internal files:

```
backend/modules/persona/
  _memory_repository.py      ← MongoDB operations for journal + memory body
  _memory_extraction.py      ← extraction job handler
  _memory_consolidation.py   ← dreaming job handler
  _memory_assembly.py        ← RAG assembly for prompt injection
```

Shared contracts:

```
shared/dtos/memory.py         ← JournalEntryDto, MemoryBodyDto, MemoryBodyVersionDto
shared/events/memory.py       ← all memory events
shared/topics.py              ← MEMORY_* topic constants
```

---

## Open Questions

### Cross-Persona Memory

Some facts (user's name, profession, preferences) are universal. Currently each
persona must learn these independently. Options:

- **Global user memory** layer that all personas can read (separate from per-persona memory)
- **Rely on `about_me`** field (already exists, user-maintained)
- **Do nothing** — each persona learns independently (simplest, most privacy-respecting)

The `about_me` field partially covers this but is manual. Decision needed.

### Tool-Based Retrieval (Phase 2)

The current design is injection-based. `FOR_LATER.md` describes a tool-based
approach where models query their memory store via tools. This is not
contradictory — injection works as Phase 1, tool-based retrieval can be added
later for more granular, token-efficient access. The structured memory body
sections prepare for this transition.

### Memory Body Structure

Should the memory body have enforced sections (facts, preferences, relationships,
events) or should the LLM organise it freely? Structured sections help with
prioritisation and future tool-based retrieval but add complexity to the
consolidation prompt.

### Extraction Output Format

The extraction LLM needs to produce structured output. Options:

- **JSON array** of `{content, timestamp, category}` — precise but may fail
  with weaker models
- **Markdown list** with metadata — more robust but needs parsing
- **Structured output / JSON mode** — if the model supports it

Decision depends on which models users will actually run.
