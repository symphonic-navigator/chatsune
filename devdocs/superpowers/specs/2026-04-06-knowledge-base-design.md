# Knowledge Base System -- Design Spec

**Date:** 2026-04-06
**Status:** Draft
**Module:** `backend/modules/knowledge/`

---

## Overview

A privacy-first knowledge base system that lets users organise reference material into
libraries and documents, embed them for semantic search, and make them available to
personas and chat sessions. The LLM decides when to search via a dedicated tool call.

### Key Principles

- **Libraries are the unit of assignment** -- never individual documents
- **Tool-based retrieval** -- the LLM decides when to search, no blind RAG
- **Transparency** -- users can see exactly which chunks were retrieved and why
- **NSFW-aware** -- libraries carry an NSFW flag, sanitised mode hides them globally

---

## Data Model

### `knowledge_libraries` Collection

| Field            | Type              | Notes                              |
|------------------|-------------------|------------------------------------|
| `_id`            | str (UUID)        | Primary key                        |
| `user_id`        | str               | Owner                              |
| `name`           | str               | Max 200 chars                      |
| `description`    | str \| None       | Max 1000 chars                     |
| `nsfw`           | bool              | Default False                      |
| `document_count` | int               | Denormalised, updated on add/delete|
| `created_at`     | datetime          |                                    |
| `updated_at`     | datetime          |                                    |

### `knowledge_documents` Collection

| Field              | Type         | Notes                                          |
|--------------------|--------------|-------------------------------------------------|
| `_id`              | str (UUID)   | Primary key                                     |
| `user_id`          | str          | Owner                                           |
| `library_id`       | str          | Foreign key to library                          |
| `title`            | str          | Max 500 chars                                   |
| `content`          | str          | Full text (Markdown or plain)                   |
| `media_type`       | str          | `"text/markdown"` or `"text/plain"`             |
| `size_bytes`       | int          |                                                 |
| `chunk_count`      | int          | Denormalised, set after chunking                |
| `embedding_status` | str          | `pending` / `processing` / `completed` / `failed` |
| `embedding_error`  | str \| None  | Error message on failure                        |
| `retry_count`      | int          | 0-3, auto-retry up to 3 then manual             |
| `created_at`       | datetime     |                                                 |
| `updated_at`       | datetime     |                                                 |

### `knowledge_chunks` Collection

| Field          | Type         | Notes                                     |
|----------------|--------------|-------------------------------------------|
| `_id`          | str (UUID)   | Primary key                               |
| `user_id`      | str          | Owner (for vector search filtering)       |
| `library_id`   | str          | For filtering by assigned libraries       |
| `document_id`  | str          | Parent document                           |
| `chunk_index`  | int          | 0-based position in document              |
| `text`         | str          | Chunk content                             |
| `heading_path` | list[str]    | Breadcrumb of Markdown headings           |
| `preroll_text` | str          | Formatted heading hierarchy as context    |
| `token_count`  | int          |                                           |
| `vector`       | list[float]  | 768 dimensions, MongoDB Vector Search     |

### Indexes

- `knowledge_libraries`: `user_id`, compound `(user_id, nsfw)`
- `knowledge_documents`: `(user_id, library_id)`, `(user_id, embedding_status)`
- `knowledge_chunks`: `(user_id, document_id)`, MongoDB Vector Search index on `vector` with `user_id` pre-filter

### Assignments (no separate collection)

- `personas` collection gains field `knowledge_library_ids: list[str]`
- `chat_sessions` collection gains field `knowledge_library_ids: list[str]`
- Always library IDs only -- never individual documents

---

## Chunking Algorithm

Ported 1:1 from Prototype 2 (`DocumentChunker`). Lives in `_chunker.py`.

### Parameters (hardcoded for now, configurable later)

- **Max tokens per chunk:** 512
- **Merge threshold:** 64 tokens (small chunks merged with neighbours)
- **Preroll lines:** 3 (context from parent section)

### Algorithm

1. **Heading split** -- regex `^#{1,6}\s+(.+)$`, maintains heading hierarchy
2. **Token limit check** -- sections under limit become chunk candidates
3. **Oversized section splitting** (fallback chain):
   - Paragraph boundaries (double newline)
   - Sentence boundaries (`.` / `!` / `?`)
   - Hard token split (word-by-word) -- last resort
4. **Small chunk merging** -- adjacent chunks with same heading parent merged if combined <= max tokens
5. **Preroll generation** -- first N lines of parent section prepended as context

---

## Backend Module

### Structure

```
backend/modules/knowledge/
  __init__.py       -- Public API: KnowledgeService, router, init_indexes
  _repository.py    -- MongoDB CRUD for all 3 collections
  _handlers.py      -- FastAPI REST endpoints
  _chunker.py       -- Chunking algorithm (port from Prototype 2)
  _retrieval.py     -- Vector search & tool executor
```

### REST Endpoints

```
# Libraries
GET    /api/knowledge/libraries                              -- list user's libraries
POST   /api/knowledge/libraries                              -- create library
PUT    /api/knowledge/libraries/{id}                         -- update (name, description, nsfw)
DELETE /api/knowledge/libraries/{id}                         -- delete (cascades docs + chunks)

# Documents
GET    /api/knowledge/libraries/{id}/documents               -- list documents in library
POST   /api/knowledge/libraries/{id}/documents               -- create document (triggers embedding)
GET    /api/knowledge/libraries/{id}/documents/{doc_id}      -- get document with content
PUT    /api/knowledge/libraries/{id}/documents/{doc_id}      -- update (re-embed on content change)
DELETE /api/knowledge/libraries/{id}/documents/{doc_id}      -- delete (chunks cleanup)
POST   /api/knowledge/libraries/{id}/documents/{doc_id}/retry -- manual embedding retry

# Persona assignment (Knowledge module provides data, Persona module stores it)
GET    /api/personas/{id}/knowledge                          -- assigned library IDs
PUT    /api/personas/{id}/knowledge                          -- set library IDs

# Session ad-hoc assignment (Knowledge provides data, Chat module stores it)
GET    /api/chat/sessions/{id}/knowledge                     -- assigned library IDs
PUT    /api/chat/sessions/{id}/knowledge                     -- set library IDs
```

### Embedding Flow

1. Document created/updated -> `embedding_status = "pending"`
2. Knowledge chunks content via `_chunker.py`
3. Knowledge calls `embedding.embed_texts(chunk_texts, reference_id=doc_id, correlation_id)`
4. Status -> `"processing"`
5. Knowledge subscribes to `EmbeddingBatchCompleted` -> stores vectors in `knowledge_chunks`
6. Status -> `"completed"`, publishes `KNOWLEDGE_DOCUMENT_EMBEDDED`
7. On `EmbeddingError`: increment `retry_count`, auto-retry up to 3, then `"failed"` + toast event

### Re-embedding on Content Change

When a document's content is updated:
1. Delete existing chunks for that document from `knowledge_chunks`
2. Re-chunk the new content
3. Re-run embedding flow from step 1

### Retrieval Flow (Tool)

1. LLM calls `knowledge_search(query: str)` tool
2. `_retrieval.py` resolves effective libraries: persona `knowledge_library_ids` + session `knowledge_library_ids`
3. Sanitised mode: filters out libraries with `nsfw = True`
4. `embedding.query_embed(query)` for query vector (blocking, high-priority)
5. MongoDB Vector Search on `knowledge_chunks` with filter: `user_id` + `library_id in [effective_ids]`
6. Top-5 chunks returned, formatted with preroll + heading path + content
7. Publishes `KNOWLEDGE_SEARCH_COMPLETED` with retrieved chunks for frontend pills

---

## Events & Topics

### New Topics (`shared/topics.py`)

```python
KNOWLEDGE_LIBRARY_CREATED        = "knowledge.library.created"
KNOWLEDGE_LIBRARY_UPDATED        = "knowledge.library.updated"
KNOWLEDGE_LIBRARY_DELETED        = "knowledge.library.deleted"
KNOWLEDGE_DOCUMENT_CREATED       = "knowledge.document.created"
KNOWLEDGE_DOCUMENT_UPDATED       = "knowledge.document.updated"
KNOWLEDGE_DOCUMENT_DELETED       = "knowledge.document.deleted"
KNOWLEDGE_DOCUMENT_EMBEDDING     = "knowledge.document.embedding"
KNOWLEDGE_DOCUMENT_EMBEDDED      = "knowledge.document.embedded"
KNOWLEDGE_DOCUMENT_EMBED_FAILED  = "knowledge.document.embed_failed"
KNOWLEDGE_SEARCH_COMPLETED       = "knowledge.search.completed"
```

### Event Payloads (`shared/events/knowledge.py`)

- `KnowledgeLibraryCreatedEvent` -- full library DTO
- `KnowledgeLibraryUpdatedEvent` -- full library DTO (post-update)
- `KnowledgeLibraryDeletedEvent` -- `library_id` only
- `KnowledgeDocumentCreatedEvent` -- document DTO (no content, with status)
- `KnowledgeDocumentUpdatedEvent` -- document DTO (no content, with status)
- `KnowledgeDocumentDeletedEvent` -- `library_id` + `document_id`
- `KnowledgeDocumentEmbeddingEvent` -- `document_id`, `chunk_count`, `retry_count`
- `KnowledgeDocumentEmbeddedEvent` -- `document_id`, `chunk_count`
- `KnowledgeDocumentEmbedFailedEvent` -- `document_id`, `error`, `retry_count`, `recoverable: bool`
- `KnowledgeSearchCompletedEvent` -- `session_id`, `results: list[RetrievedChunkDto]`

### DTOs (`shared/dtos/knowledge.py`)

- `KnowledgeLibraryDto` -- id, name, description, nsfw, document_count, created_at, updated_at
- `KnowledgeDocumentDto` -- id, library_id, title, media_type, size_bytes, chunk_count, embedding_status, embedding_error, created_at, updated_at (no content)
- `KnowledgeDocumentDetailDto` -- extends DocumentDto + `content: str`
- `CreateLibraryRequest` / `UpdateLibraryRequest`
- `CreateDocumentRequest` / `UpdateDocumentRequest`
- `RetrievedChunkDto` -- library_name, document_title, heading_path, preroll_text, content, score

### Fan-out

All knowledge events target `target_user_ids=[user_id]` -- only the owner receives them.

---

## Frontend

### Knowledge Tab (User Modal)

Located in the existing `KnowledgeTab.tsx` placeholder.

- **Library list** -- expandable rows showing name, document count, edit/delete actions
- **NSFW indicator** -- 💋 emoji on NSFW libraries
- **Warning indicator** -- ⚠ on libraries with failed embeddings (consistent with API key warnings)
- **Document list** (within expanded library) -- title, embedding status dot, size, rename/delete actions
- **Embedding status dots:**
  - Green (solid) = completed
  - Yellow (pulsing) = processing
  - Red = failed (click to retry)
- **"+ New Library"** button at top right
- **"+ Add Document"** dashed button within each expanded library
- **Document click** opens Document Editor modal

### Document Editor Modal

- Title input field (editable)
- Markdown/plain text toggle
- Content editor area
- Live preview panel (Markdown rendering)
- File upload button (.md, .txt) -- loads file content into editor
- Save / Delete / Cancel buttons
- Unsaved changes prompt
- Delete with two-step confirmation
- On save with content change: automatic re-embedding triggered

### Knowledge Tab (Persona Overlay)

Located in the existing persona overlay `KnowledgeTab.tsx` placeholder.

- **Assigned libraries list** -- styled in persona's chakra colour
- **Each library row:** name, document count, 💋 if NSFW, × remove button
- **"+ Assign Library"** dropdown showing unassigned libraries only
- **Sanitised mode:** NSFW libraries hidden entirely
- **Warning indicator** on libraries with embedding issues

### Chat Topbar -- Ad-hoc Knowledge

- **🎓 Mortarboard icon** in topbar (lila background tint `rgba(140,118,215,0.1)`)
- **Dropdown on click:** shows libraries NOT already assigned to the persona
- **Checkbox toggle** per library for session-scoped assignment
- **Subtitle text:** "Libraries already assigned to [persona] are not shown here."
- **Sanitised mode:** NSFW libraries hidden from dropdown

### Knowledge Pills (Chat)

- **Tool call activity pill** during search: lila with spinner, shows query text
  - Colour: `#8C76D7` with `rgba(140,118,215,...)` background
- **Retrieved knowledge pills** after search: compact pills with document title + similarity score
  - 📚 icon prefix
  - Multiple chunks from same document = separate pills
- **Click to expand:** inline expansion showing:
  - Library name (monospace, small) > Document title (lila)
  - Heading path as breadcrumb
  - Chunk content preview
  - Similarity score
- **"RETRIEVED KNOWLEDGE"** label above pills (monospace, subtle)

---

## Sanitised Mode Integration

The existing `useSanitisedMode` store already filters personas by `nsfw`. Knowledge
extends this consistently:

- **User Modal Knowledge Tab:** hide libraries with `nsfw = True`
- **Persona Overlay Knowledge Tab:** hide NSFW libraries from assignment dropdown
- **Chat Topbar Dropdown:** hide NSFW libraries from ad-hoc assignment
- **Retrieval:** filter out NSFW libraries from effective library set before vector search
- **Backend enforcement:** the `knowledge_search` tool executor checks sanitised mode
  and excludes NSFW libraries server-side (frontend filtering alone is not sufficient)

### Sanitised Mode State

Sanitised mode is currently a frontend-only localStorage toggle. For knowledge retrieval
filtering to work server-side, the sanitised mode state must be available to the backend.

**Decision:** The `chat_sessions` document carries a `sanitised: bool` field. The frontend
sets this on session create and updates it when the user toggles sanitised mode. The
`knowledge_search` tool executor reads it from the session to filter NSFW libraries.
This avoids per-message overhead and keeps the state consistent across reconnects.

---

## Scope Boundaries

### In Scope (this spec)

- Knowledge module (backend): libraries, documents, chunks, CRUD, embedding orchestration
- Chunking algorithm (port from Prototype 2)
- Retrieval via tool call with vector search
- Shared contracts (DTOs, events, topics)
- Frontend: Knowledge Tab (User Modal), Knowledge Tab (Persona Overlay), Document Editor,
  Chat Topbar ad-hoc dropdown, Knowledge Pills in chat
- NSFW / sanitised mode integration
- Embedding status tracking with retry logic
- Toast notifications on final embedding failure

### Out of Scope

- URL import (fetch webpage as Markdown) -- separate feature
- Configurable chunking parameters -- later, current defaults are good
- Sharing libraries between users -- not planned
- Knowledge analytics / usage stats -- not planned
