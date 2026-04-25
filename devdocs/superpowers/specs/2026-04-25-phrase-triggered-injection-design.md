# Phrase Triggered Injection (PTI) — Design Spec

**Status:** Draft, awaiting user review
**Date:** 2026-04-25
**Authors:** Chris (product / design), Claude (architecture / spec)

## 1. Purpose

Allow users to attach **trigger phrases** to Knowledge Base documents.
When a phrase appears in a user message, the latest version of the
document is **deterministically injected** into that message as hidden
context — independent of whether the LLM chooses to call the
`knowledge_search` tool.

This is conceptually similar to "lorebooks" in SillyTavern, but adapted
to Chatsune's document-centric model and prepared for end-to-end
encryption (E2EE) at rest.

### Motivation

Chatsune already has an LLM-callable `knowledge_search` tool that
performs cosine-similarity retrieval over chunked documents. This works
well for tool-eager models, where the model proactively queries the KB
when it senses missing knowledge. It works poorly for tool-shy models,
which often fail to invoke the tool even when needed.

PTI gives the **user** explicit, deterministic control: when a phrase is
mentioned, the relevant document is guaranteed to be in the LLM context.
PTI and `knowledge_search` coexist on the same documents; they are two
orthogonal retrieval paths serving different model "personalities".

## 2. Scope

### In scope (Phase 1)

- Trigger-phrase CRUD on Knowledge Base documents
- Per-library default refresh frequency, per-document override
- In-RAM trigger index per session, event-driven invalidation
- Substring matching on normalised strings (international, including emoji)
- Hard caps on injection volume per message
- Frontend pill rendering, reusing existing `KnowledgePills` component
- Architecture decisions that make E2EE possible later (no implementation)

### Out of scope (deferred to later phases)

- E2EE encryption / decryption of trigger phrases and document content
- Compact-and-Continue interaction (compaction + post-compaction re-inject)
- Project-level Knowledge Base attachments (persona + session only)
- Match grading or scoring (simple hit / no-hit suffices)
- Regular-expression triggers (substring matching is sufficient; can be
  added additively later if needed)

## 3. Background — Existing Codebase

The following components already exist and are referenced throughout
this spec.

| Component | Path | Role |
|---|---|---|
| `KnowledgeDocument` | `backend/modules/knowledge/_models.py` | KB document model |
| `KnowledgeLibrary` | `backend/modules/knowledge/_models.py` | KB library model |
| `ChatSession` | `backend/modules/chat/_models.py` | Chat session model |
| `ChatMessage` | `backend/modules/chat/_models.py` | Chat message model |
| `_orchestrator.py` | `backend/modules/chat/_orchestrator.py` | LLM-call orchestration |
| `_context.py` | `backend/modules/chat/_context.py` | Context-window pair selection |
| `event_bus.py` | `backend/ws/event_bus.py` | Event-bus + `_FANOUT` mapping |
| `KnowledgePills.tsx` | `frontend/src/features/chat/` | Pills rendering for `knowledge_context` |
| `knowledge_search` tool | `backend/modules/chat/_orchestrator.py:160-174` | Existing embedding-based retrieval |
| `knowledge_context` field | `ChatMessageDto` | Existing per-message retrieval payload |

`knowledge_context` is reused (not replaced) by PTI — see Section 5.

## 4. User-Facing Behaviour

### 4.1 Authoring trigger phrases

In the document edit UI, the user adds trigger phrases via a tag-input
control:

```
Trigger phrases
[andromedagalaxie ×] [sigma-sektor ×] [maartje voss ×]
[+ add phrase…]
```

- Tags display the **normalised** form (see Section 6.1) so the user
  understands exactly what will be matched.
- International characters and emoji are supported.
- No "enable trigger phrases" toggle — the editor is always available.
  Empty list = no triggers, no PTI activity for this document.

### 4.2 Refresh frequency

Each library has a `default_refresh` setting; each document can override
it. The setting controls how many user messages must pass between
re-injections of the same document.

| Setting | n (user messages) | Use case |
|---|---|---|
| `rarely` | 10 | Detail-level lore, infrequently relevant |
| `standard` (default) | 7 | General-purpose worldbuilding |
| `often` | 5 | Stem triggers — central to the conversation |

Document-level UI shows the inherited value:
`Refresh frequency: [Inherit (Standard) ▼]`.

### 4.3 Match and injection at runtime

When a user sends a message:

1. The message is normalised.
2. Trigger phrases of all attached library documents (persona libraries
   + session ad-hoc libraries) are checked as substrings of the
   normalised message, in order of appearance.
3. For each hit, cooldown is checked: if the document was injected
   within the last `n` user messages, skip it.
4. Surviving hits are injected into the user message's `knowledge_context`
   with `source = "trigger"`.
5. Caps are applied: max 10 documents and max 8,000 hidden-context
   tokens per message — whichever hits first stops further injections.
6. The user's `pti_last_inject` map on the session is updated for each
   injected document.

The injected content is the **full document body** — PTI does not chunk.

### 4.4 Pills

Reuses the existing `KnowledgePills` component with a `source` field on
each entry:

| `source` | Icon | Tooltip detail |
|---|---|---|
| `search` | `book-open` (existing) | Retrieval score, chunk index |
| `trigger` | `sparkles` (new) | "Triggered by: '<phrase>'" |

If injection caps were exceeded, an additional muted pill is appended:
`[+3 limited]`. Click expands to show the dropped document titles.

## 5. Data Model

### 5.1 New / changed fields

| Model | Field | Type | Default | Notes |
|---|---|---|---|---|
| `KnowledgeDocument` | `trigger_phrases` | `list[str]` | `[]` | Already-normalised strings |
| `KnowledgeDocument` | `refresh` | `Literal["rarely","standard","often"] \| None` | `None` | `None` = inherit from library |
| `KnowledgeLibrary` | `default_refresh` | `Literal["rarely","standard","often"]` | `"standard"` | |
| `ChatSession` | `pti_last_inject` | `dict[str, int]` | `{}` | `doc_id → user-message index of last injection` |
| `ChatSession` | `user_message_counter` | `int` | `0` | Monotonic counter, ++ on each user message |
| `ChatMessage` | `knowledge_context[].source` | `Literal["search","trigger"]` | `"search"` | Discriminator on existing list |
| `ChatMessage` | `knowledge_context[].triggered_by` | `str \| None` | `None` | The phrase that triggered (only when `source="trigger"`) |
| `ChatMessage` | `pti_overflow` | `{ dropped_count: int, dropped_titles: list[str] } \| None` | `None` | Set when caps were applied |

Pydantic defaults handle existing documents — no migration script
required (see Section 8).

### 5.2 Removed from original brief

The following fields from the original brief are **dropped**:

- `trigger_phrases[].mode` (regex was cut; mode discriminator is moot)
- `KnowledgeDocument.content_hash` (cooldown-based re-inject obviates
  hash-based change detection)
- `ChatSession.pti_injected: list[{doc_id, content_hash}]` (replaced by
  the simpler `pti_last_inject` map)
- `ChatMessage.hidden_context` (we reuse the existing `knowledge_context`
  field with a `source` discriminator instead of introducing a parallel
  field)

## 6. Algorithms

### 6.1 Normalisation

Three steps, applied identically to trigger phrases on save and to user
messages on match:

```python
import unicodedata

def normalise(s: str) -> str:
    s = unicodedata.normalize("NFC", s)
    s = s.casefold()
    s = " ".join(s.split())  # collapses any whitespace class to single ASCII space, trims
    return s
```

Notes:
- `casefold()` is preferred over `lower()` for Unicode-correct
  case-insensitive comparison (handles ß → ss, Turkish dotted I, etc.).
- No punctuation stripping. `"Andromeda-Galaxie!"` → `"andromeda-galaxie!"`.
- No ASCII-only filter. Cyrillic, CJK, emoji all pass through unchanged.
- The function is idempotent: `normalise(normalise(s)) == normalise(s)`.

**Frontend mirror.** A TypeScript implementation lives in
`frontend/src/features/knowledge/normalisePhrase.ts` for live preview.
Backend is authoritative and re-normalises on save.

> **Insight required:** add an INSIGHTS.md entry analogous to the xAI
> voice-tags entry: "PTI normalisation lives in two files
> (`backend/modules/knowledge/_pti_normalisation.py` and
> `frontend/src/features/knowledge/normalisePhrase.ts`); they must be
> kept in sync manually."

### 6.2 Match algorithm

Per session, an in-memory `TriggerIndex`:

```python
class TriggerIndex:
    # phrase -> list of doc_ids (multiple docs can share a phrase)
    phrase_to_docs: dict[str, list[str]]
```

On each user message:

```python
def match(message: str, index: TriggerIndex) -> list[tuple[str, str, int]]:
    """Returns (doc_id, phrase, position) tuples in order of appearance."""
    norm = normalise(message)
    hits: list[tuple[str, str, int]] = []
    for phrase, doc_ids in index.phrase_to_docs.items():
        pos = norm.find(phrase)
        if pos >= 0:
            for doc_id in doc_ids:
                hits.append((doc_id, phrase, pos))
    hits.sort(key=lambda x: x[2])  # by position in message
    return hits
```

For Phase 1 we use a naive scan over the index. Substring search on a
normalised string with up to a few hundred trigger phrases is well
within microsecond range. Aho-Corasick is a future optimisation if a
session attaches libraries with thousands of triggers.

### 6.3 Cooldown

Cooldown is measured in **user messages** on the session:

```python
def is_cooled_down(doc_id: str, session: ChatSession, n: int) -> bool:
    last = session.pti_last_inject.get(doc_id)
    if last is None:
        return True
    return (session.user_message_counter - last) >= n
```

Refresh-frequency to `n`:

| Setting | n |
|---|---|
| `rarely` | 10 |
| `standard` | 7 |
| `often` | 5 |

Document's effective n:
`document.refresh or library.default_refresh`.

### 6.4 Injection caps

Apply in this order to the position-sorted hit list:

1. Iterate hits.
2. Skip duplicate `doc_id` (same doc triggered by multiple phrases in
   one message → inject once).
3. Skip if not cooled down.
4. Estimate token count of document body via the existing tokeniser
   used in `_context.py`.
5. If running totals exceed **either** 10 documents **or** 8,000
   tokens, drop remaining candidates and record them in
   `pti_overflow.dropped_titles`.

The 8,000-token cap protects the chat-history pair-selection budget.
For a typical 80k-token model with ~50k available for chat, even a full
8k injection still leaves comfortable room for history.

### 6.5 Conflict (multiple docs, same phrase)

Both documents are injected (subject to caps). This was a deliberate
user-experience decision: forbidding it would frustrate users who
intentionally maintain related lore documents under the same trigger.

### 6.6 Per-document content cap

A document is **only PTI-eligible** if its content fits within
**5,000 tokens / 20,000 characters**. Trigger phrases on larger
documents are rejected at save time with a clear error message:

> "PTI documents must stay under 5,000 tokens (~20,000 characters).
> Split this document into smaller, focused entries."

The cap is enforced when **either**:
- The user adds the first trigger phrase to a document, or
- The user edits content of a document that already has trigger phrases.

Documents **without** trigger phrases are not subject to this cap —
they remain available for embedding-based `knowledge_search` retrieval
at any size.

Rationale: PTI documents are canonical, deterministic lore atoms.
A 50,000-character FTL-drive treatise blasted into every user message
that mentions "drive" defeats the point. Forcing decomposition into
focused sub-documents keeps both injections and overall context budgets
healthy. Users who want sprawling exposition can still rely on
embedding-search retrieval for chunked access.

Validation order on save:
1. Cheap char-length check: `len(content) > 20_000` → reject early.
2. Exact token count via the same tokeniser used in `_context.py`.
3. If both above pass and `trigger_phrases` is non-empty → accept.

## 7. Architecture

### 7.1 Module boundaries

PTI lives in the existing `knowledge` module. New internal files:

```
backend/modules/knowledge/
  _pti_normalisation.py    ← normalisation function
  _pti_index.py            ← TriggerIndex + cache
  _pti_service.py          ← public match-and-inject method
```

Public API on `KnowledgeService` (extended):

```python
class KnowledgeService:
    async def get_pti_injections(
        self,
        session_id: str,
        message: str,
    ) -> tuple[list[KnowledgeContextItem], PtiOverflow | None]:
        """
        Match trigger phrases in `message` against the in-RAM index for
        this session, apply cooldowns and caps, mutate
        session.pti_last_inject, and return the items to inject plus
        any overflow info.
        """
```

The `chat` module calls this method via the public `KnowledgeService`
API. No internal imports across module boundaries.

### 7.2 Lifecycle integration

Pre-persist on the user message:

```
WS handle_chat_send
  ├── ChatSession.user_message_counter += 1
  ├── KnowledgeService.get_pti_injections(session_id, content)
  │     → returns (items, overflow)
  ├── ChatRepository.create_message(
  │       knowledge_context = items,
  │       pti_overflow      = overflow,
  │       ...
  │   )
  ├── publish CHAT_MESSAGE_CREATED          ← contains knowledge_context + pti_overflow
  └── run_inference(...)                     ← unchanged
```

Cooldown updates and `user_message_counter` increment happen inside
`get_pti_injections`, in the same transaction (or close to it) as
`create_message`.

### 7.3 Event topology

**No new topics required.** The existing `Topics.CHAT_MESSAGE_CREATED`
carries the extended `knowledge_context` (with `source` discriminator)
and the new `pti_overflow` field. Its `_FANOUT` mapping is already
correct (target user only, persisted to Redis Stream).

### 7.4 In-RAM trigger index

A single backend-process singleton:

```python
class PtiIndexCache:
    _per_session: dict[str, TriggerIndex]  # session_id -> index
```

Loaded lazily on first user message of a session, keyed by `session_id`.

**Cache invalidation events** subscribed by `PtiIndexCache`:

| Topic | Action |
|---|---|
| `KNOWLEDGE_DOCUMENT_CREATED` | Add document's phrases to all session indices that include this library |
| `KNOWLEDGE_DOCUMENT_UPDATED` | Remove old, add new phrases for affected sessions |
| `KNOWLEDGE_DOCUMENT_DELETED` | Remove phrases from affected sessions |
| `LIBRARY_ATTACHED_TO_SESSION` | Load library phrases into the session's index |
| `LIBRARY_DETACHED_FROM_SESSION` | Drop library phrases from the session's index |
| `LIBRARY_ATTACHED_TO_PERSONA` | Fan out to all live sessions of this persona |
| `LIBRARY_DETACHED_FROM_PERSONA` | Fan out to all live sessions of this persona |

Multi-worker correctness: events flow through Redis Streams, so every
backend worker receives every invalidation event and updates its own
local index. There is no shared mutable state across workers.

> **Caveat for some of the above topics.** Some library-attach /
> detach events may not yet exist as first-class topics — they need to
> be added during implementation if missing. The plan should verify and
> create them as needed.

### 7.5 Logging (Claude-oriented)

Per CLAUDE.md, the backend emits structured logs at decision points.
PTI emits at minimum:

```
pti.match  session_id=… user_message_count=… hits=[…] dropped_cooldown=[…]
pti.inject session_id=… injected=[doc_id,…] overflow_count=N tokens=NNNN
pti.cache.load   session_id=… library_ids=[…] phrase_count=N
pti.cache.invalidate session_id=… reason=… affected_doc_ids=[…]
```

## 8. Migration

Following the post-2026-04-15 "no more wipes" rule, but no migration
script needed:

- All new fields have Pydantic defaults.
- Existing documents deserialize without error.
- Fields are written on first save of an updated document.
- Library export / import (per INS-020) must round-trip the new
  fields. **Acceptance criterion** in Section 11 covers this.

If operational consistency becomes an issue later (e.g. for analytics
queries), an idempotent backfill script can be added at
`backend/migrations/m_YYYY_MM_DD_pti_backfill.py`.

## 9. E2EE Future-Compatibility Constraints

Implementation deferred. The following architectural decisions are
made now to keep E2EE viable later:

1. **No MongoDB full-text or regular index on `trigger_phrases`.**
   Matching happens exclusively against the in-RAM index. MongoDB
   indices remain on non-sensitive fields only (`library_id`, `_id`).
2. **Decryption boundary = cache-load + invalidation events.**
   Plain-text trigger phrases exist only inside `PtiIndexCache`, never
   on disk in plaintext (post-E2EE). Outside the cache, trigger phrases
   are only ever encrypted.
3. **`KnowledgeDocument.content` and `KnowledgeDocument.trigger_phrases`
   are encrypted together** (single envelope per document) — no partial
   decryption paths.
4. **PTI-Service is user-scoped, not globally shared.** The cache key
   includes `session_id`; cross-user contamination is structurally
   impossible.
5. **No content hashes on encrypted fields.** Already accomplished by
   dropping the `content_hash` field.
6. **Cache lifetime is bounded by session lifetime.** When the session
   ends, the index entry is dropped — encrypted-at-rest plaintext does
   not linger in memory.

## 10. Performance Notes

### Expected workload

- Typical session: 1–5 attached libraries, 10–100 documents per library
- Typical document: 0–10 trigger phrases
- Per-session phrase count: 100s, peak low thousands

### Phase 1 implementation: naive substring scan

For up to a few thousand phrases per session, a linear scan over the
index dictionary is sub-millisecond on modern hardware. No
optimisation needed.

### Future scaling path (not Phase 1)

If sessions ever attach libraries totalling 10k+ phrases, switch to an
Aho-Corasick automaton built once on cache load. The on-demand
match-time cost stays linear in message length.

## 11. Acceptance Criteria

- [ ] User can add, edit, and remove trigger phrases on a Knowledge
      Base document via API and UI
- [ ] Phrases are normalised on save (NFC + casefold + whitespace
      collapse)
- [ ] Frontend tag-input shows normalised form in tags
- [ ] Library has `default_refresh` setting; document can override
- [ ] PTI-Index is loaded on first user message of a session
- [ ] PTI-Index is invalidated on relevant KB-events
      (Created/Updated/Deleted, Library Attached/Detached to Session
      and Persona)
- [ ] User-message matching uses substring search on normalised
      strings
- [ ] Multi-word trigger phrases match correctly (whitespace robustness)
- [ ] Emoji and international characters work as triggers
- [ ] Cooldown prevents re-injection within `n` user messages
- [ ] Caps enforced: max 10 documents, max 8,000 tokens hidden-context
      per message
- [ ] Multi-document conflicts on same phrase: both injected (subject
      to caps)
- [ ] Per-document size cap (5,000 tokens / 20,000 chars) enforced at
      save time when document has at least one trigger phrase
- [ ] Documents without trigger phrases are not size-capped
- [ ] Pills reuse `KnowledgePills` with `source` discriminator and
      different icon for `source="trigger"`
- [ ] Overflow pill shown when caps applied; click expands dropped
      titles
- [ ] No MongoDB full-text or text-search index on `trigger_phrases`
- [ ] `pti_overflow` and extended `knowledge_context` are persisted to
      `ChatMessage`
- [ ] `CHAT_MESSAGE_CREATED` event carries the full payload — no second
      event needed
- [ ] Library export / import round-trips `trigger_phrases`,
      `refresh`, and `default_refresh`
- [ ] Backend tests cover: normalisation idempotency, match correctness
      (single + multi-word + emoji + Unicode), cooldown logic, cap
      enforcement, cache invalidation
- [ ] Frontend tests cover: pill source rendering, overflow pill
      behaviour, tag-input normalisation preview
- [ ] `INSIGHTS.md` entry added for backend / frontend normalisation
      sync requirement
- [ ] Build clean: `pnpm run build` succeeds, `uv run python -m
      py_compile` on changed backend files succeeds
- [ ] Manual end-to-end smoke: a worldbuilding session with 3 attached
      libraries demonstrates the full feature

## 12. Open Questions for Implementation

These are deferred to the implementation plan, not blocking design
acceptance:

1. **Token-counting for the 8,000-token cap.** Use the same tokeniser
   that `_context.py` uses, or a heuristic? Decide during
   implementation, document choice.
2. **Library-attach / detach event topics.** Verify whether
   `LIBRARY_ATTACHED_TO_SESSION` etc. exist as published topics today;
   add if missing.
3. ~~Document-content size limit for PTI.~~ **Resolved:** 5,000 tokens /
   20,000 characters per PTI-eligible document, enforced at save time.
   See Section 6.6.
