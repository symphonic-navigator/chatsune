# `write_journal_entry` — Server-Side Tool for Personas

**Date:** 2026-04-11
**Status:** Draft, awaiting implementation plan
**Scope:** Backend (new tool, new memory public API, new event) + Frontend (event subscription, info toast)

## Summary

Add a new server-side tool `write_journal_entry` that allows a persona (the LLM) to autonomously record an uncommitted journal entry about the user when it believes it has just learned something genuinely significant and lasting. The entry appears live in the journal UI and triggers an info toast naming the persona. The tool is exposed through a new toggleable tool group `journal` so users can disable the behaviour per session.

## Motivation

Today, uncommitted journal entries are only produced by the extraction service running over past conversation turns. This is a retroactive, mechanical process. A persona cannot, in the moment, say "I have just learned something important about Chris — I want to remember this." The new tool closes that gap and enables natural in-conversation acknowledgements like:

> "Noted — I'll remember that 'principle of least astonishment' is a core value for you."

## Non-Goals

- Auto-committing entries. All entries created through this tool remain in `state: "uncommitted"` and require explicit user commitment via the existing journal UI, same as extraction-produced entries.
- Rate limiting or deduplication. The tool relies purely on LLM judgement, guided by its description. If abuse is observed, hard limits can be added later.
- Editing or deleting entries through the tool. The persona can only create.

## Tool Definition

**Name:** `write_journal_entry`
**Group:** `journal` (new, server-side, toggleable)

**Parameters (JSON Schema):**

```json
{
  "type": "object",
  "required": ["content", "category"],
  "properties": {
    "content": {
      "type": "string",
      "description": "The insight about the user, written in natural prose as the persona understands it. Third person, specific and concrete."
    },
    "category": {
      "type": "string",
      "enum": ["preference", "fact", "relationship", "value", "insight", "projects", "creative"],
      "description": "Which aspect of the user this entry captures."
    }
  }
}
```

**Tool description (shown to the LLM):**

> Record a lasting observation about the user in your private journal. Use this ONLY when you believe you have just learned something genuinely significant — something that will meaningfully change how you understand or relate to this person over the long term. Do NOT use this for small talk, transient context, things obvious from the conversation itself, or things you could easily infer later. The entry is uncommitted (a draft) until the user explicitly commits it. Be selective: a handful of truly impactful entries is worth more than many shallow ones.

## Architecture

### New backend artefacts

1. **`shared/topics.py`** — new constant
   `MEMORY_ENTRY_AUTHORED_BY_PERSONA = "memory.entry.authored_by_persona"`

2. **`shared/events/memory.py`** — new event
   `MemoryEntryAuthoredByPersonaEvent` with payload fields `entry: JournalEntryDto`, `correlation_id: str`, `timestamp: datetime`. Parallel shape to `MemoryEntryCreatedEvent` but a dedicated type so the frontend can distinguish it for the toast.

3. **`backend/modules/memory/__init__.py`** — new public API function
   ```python
   async def write_persona_authored_entry(
       *,
       user_id: str,
       persona_id: str,
       content: str,
       category: str,
       source_session_id: str,
       correlation_id: str,
   ) -> JournalEntryDto
   ```
   Responsibilities:
   - Call the internal `_repository.create_journal_entry(...)` (state stays `"uncommitted"`, `is_correction=False`, `auto_committed=False`).
   - Load the newly created entry as a `JournalEntryDto`.
   - Publish `MemoryEntryAuthoredByPersonaEvent` on the event bus with scope `persona:{persona_id}`.
   - Return the DTO.

4. **`backend/modules/tools/_executors.py`** — new class `JournalToolExecutor`
   - Implements the `ToolExecutor` protocol.
   - Handles `tool_name == "write_journal_entry"`.
   - Extracts `_session_id`, `_persona_id`, `_correlation_id` from arguments (same pattern as `ArtefactToolExecutor`).
   - Validates `content` and `category` (see Error Handling).
   - Calls `memory.write_persona_authored_entry(...)`.
   - Returns JSON-encoded string: `{"status": "recorded", "entry_id": "..."}` on success, `{"error": "..."}` otherwise.

5. **`backend/modules/tools/_registry.py`** — new tool group
   ```python
   ToolGroup(
       id="journal",
       side="server",
       toggleable=True,
       tool_names=["write_journal_entry"],
       definitions=[<ToolDefinition above>],
       executor=JournalToolExecutor(),
   )
   ```

6. **`backend/modules/chat/_inference.py`** — inject `_persona_id` into tool-call arguments alongside the already-injected `_session_id` and `_correlation_id`. The executor needs this to know which persona to write to.

**Module boundaries:** `tools` depends only on the public API of `memory` — no direct access to `_repository` or `_models`. This is the whole reason `write_persona_authored_entry` is added as a public function rather than having the executor reach into the repository directly.

### New frontend artefacts

7. **Journal store subscription** — subscribe to `memory.entry.authored_by_persona` in addition to the existing `memory.entry.created`. On receipt, insert the entry into the journal list exactly like `MemoryEntryCreatedEvent`.

8. **Info toast** — on receipt of `memory.entry.authored_by_persona`, show an info toast with a message like `"{persona_name} has added a journal note about you."` with click-through to the journal view. The persona name comes from the existing persona store (lookup by `entry.persona_id`).

## Data Flow

```
LLM decides: "this is genuinely impactful"
  │
  ▼
Tool call: write_journal_entry(content, category)
  │
  ▼
chat/_inference.py                           ← injects _session_id, _persona_id, _correlation_id
  │
  ▼
tools.execute_tool(user_id, "write_journal_entry", args)
  │
  ▼
JournalToolExecutor.execute()                ← unpacks args, validates, calls memory public API
  │
  ▼
memory.write_persona_authored_entry(...)     ← creates uncommitted entry, loads DTO, publishes event
  │                                              │
  │                                              ▼
  │                                          event_bus.publish(
  │                                            MEMORY_ENTRY_AUTHORED_BY_PERSONA,
  │                                            MemoryEntryAuthoredByPersonaEvent(entry=..., ...),
  │                                            scope="persona:{persona_id}"
  │                                          )
  │                                              │
  │                                              ▼
  │                                          Frontend:
  │                                            · journalStore.add(entry)
  │                                            · toast.info("{persona} added a journal note")
  │
  ▼
returns JSON: {"status": "recorded", "entry_id": "..."}
  │
  ▼
LLM sees result, can acknowledge in its reply
```

The correlation ID of the current chat turn is threaded through the executor and the event, so the event graph for a given turn can be reconstructed from logs.

## Error Handling

**Validation errors (tool-side, before any write):**

| Condition | Returned JSON |
|---|---|
| `content` missing or empty | `{"error": "content must be a non-empty string"}` |
| `category` missing or not in the enum | `{"error": "category must be one of: preference, fact, relationship, value, insight, projects, creative"}` |
| `content` longer than 2000 characters | `{"error": "content too long (max 2000 characters)"}` |
| `_persona_id` or `_session_id` missing from dispatch context | `{"error": "internal: missing session context"}` plus backend `ERROR` log with correlation ID |

**Unexpected errors (e.g. database outage):**

- Exception caught in the executor → `{"error": "failed to record entry"}` returned to the LLM, full stack trace logged with the correlation ID.
- No `ErrorEvent` is dispatched to the user. The LLM sees the `error` field in the tool result and can communicate the failure naturally in its reply ("I tried to note that, but couldn't — I'll remember it for now at least"). This matches the pattern that tool-call failures are the LLM's concern, not the global error surface.

All error returns are JSON-encoded strings (like every other executor), so the LLM can parse them and react.

## Testing

### Backend

1. **`JournalToolExecutor.execute` — happy path.** Fully valid args → executor calls `memory.write_persona_authored_entry` with the right parameters, returns `{"status": "recorded", "entry_id": "..."}`.

2. **`JournalToolExecutor.execute` — validation.** A compact parametrised test for: missing content, empty content, missing category, invalid category, content longer than 2000 chars. Each case returns the expected error JSON; `memory` is not called.

3. **`memory.write_persona_authored_entry` — integration.** Runs against a real Mongo RS0 (no mocks). Asserts that:
   - a journal entry with `state: "uncommitted"` exists in the collection,
   - `MemoryEntryAuthoredByPersonaEvent` is published on the event bus,
   - the returned DTO contains the correct fields.

4. **Tool registry smoke test.** `execute_tool(user_id, "write_journal_entry", args)` resolves to the `JournalToolExecutor` and the `"journal"` group is present in the result of `get_active_definitions()`.

### Frontend

No unit tests. The new event handler is effectively a store update plus a toast call — trivial enough to fall under the "no tests for one-liners" rule in CLAUDE.md. Manual browser verification at the end of implementation: trigger the tool via a live LLM turn, confirm that the toast appears and the entry shows up in the journal.

## Open Questions

None. Design approved in brainstorming session 2026-04-11.
