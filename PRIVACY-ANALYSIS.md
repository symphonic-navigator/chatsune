# Chatsune — Privacy Feature Analysis

**Date:** 2026-04-13
**Context:** Community requests for privacy features. This document assesses feasibility
and effort for four privacy capabilities.

---

## Current State Summary

Chatsune stores user data across **18 MongoDB collections**, two on-disk directories
(`/data/uploads/`, `/data/avatars/`), and Redis. The only data currently encrypted at
rest is LLM API keys (Fernet symmetric encryption). Passwords are bcrypt-hashed.

### Data owned per user

| Category | Collections | On-disk files |
|----------|------------|---------------|
| Identity | `users` | — |
| Personas | `personas` | avatars in `/data/avatars/` |
| Chat | `chat_sessions`, `chat_messages` | — |
| Memory | `memory_journal_entries`, `memory_bodies` | — |
| Knowledge | `knowledge_libraries`, `knowledge_documents`, `knowledge_chunks` | — |
| Storage | `storage_files` | files in `/data/uploads/{user_id}/` |
| Artefacts | `artefacts`, `artefact_versions` | — |
| Bookmarks | `bookmarks` | — |
| Projects | `projects` | — |
| LLM config | `llm_user_credentials`, `llm_model_curations`, `llm_user_model_configs` | — |
| Integrations | `user_integration_configs` | — |
| Audit | `audit_log` | — |

---

## 1. Granular Deletion (Chats & Personas)

**Question:** Can users delete individual chats and personas with zero residual data?

### Current state

**Persona deletion** (`DELETE /api/personas/{id}`) already cascades to:
- Chat sessions and messages (via `ChatRepository.delete_by_persona`)
- Memory journal entries and bodies (via `MemoryRepository.delete_by_persona`)
- Storage files — DB records and on-disk blobs (via `StorageRepository.delete_by_persona`)
- Artefacts and versions (via `ArtefactRepository.delete_by_session_ids`)
- Avatar file on disk

**Chat session deletion** (`DELETE /api/chat/sessions/{id}`) is currently **soft-delete only**
(sets `deleted_at`). Hard-delete runs 60 minutes later via background cleanup job,
which also cascades to bookmarks.

### Gaps

| Gap | Impact | Fix |
|-----|--------|-----|
| Chat soft-delete leaves data accessible for 60 min | Data not immediately gone | Add optional `?permanent=true` query param for immediate hard-delete |
| Soft-deleted chat messages remain in DB for 60 min | Same | Hard-delete messages immediately when permanent flag set |
| Knowledge libraries linked to a persona are not deleted | Orphaned knowledge data | Add cascade: delete persona → unlink or delete associated knowledge libraries |
| Bookmarks referencing deleted messages are not cleaned up on chat hard-delete (only on soft-delete expiry) | Orphaned bookmarks | Add bookmark cascade to immediate hard-delete path |
| Artefacts from deleted chat sessions are not deleted if session is soft-deleted | Orphaned artefacts | Cascade artefact deletion on hard-delete |
| Integration configs for deleted persona remain | Minor orphaned config | Add cascade: delete persona → delete integration configs for that persona |

### Effort estimate

**Small — 1-2 days.**
The cascade infrastructure already exists. This is mostly about:
- Adding a `permanent` flag to the chat delete endpoint
- Ensuring all cascades fire on immediate hard-delete (bookmarks, artefacts)
- Adding knowledge library unlinking on persona delete
- Cleaning up integration configs on persona delete
- Adding an audit log entry for each deletion

---

## 2. Data Export (Right to Access)

**Question:** Can users download all their data as a package of JSON files?

### Current state

**No export functionality exists.** There are no endpoints, utilities, or background
jobs for data export.

### Proposed design

A new endpoint `POST /api/users/me/export` that:

1. Collects all user-owned data from every collection
2. Packages it as a ZIP file containing JSON files per category:

```
chatsune-export-{username}-{date}/
  user-profile.json
  personas/
    {persona_id}.json          ← persona config + system prompt
    {persona_id}-memory.json   ← journal entries + consolidated memory bodies
  chats/
    {session_id}.json          ← session metadata + all messages
  knowledge/
    {library_id}/
      library.json             ← library metadata
      documents/
        {doc_id}.json          ← document content (no embeddings — those are derived)
  artefacts/
    {artefact_id}.json         ← artefact + all versions
  bookmarks.json
  projects.json
  files/
    {file_id}-{original_name}  ← actual uploaded files copied from disk
  integrations.json
  llm-config.json              ← model curations + configs (API keys excluded)
```

3. Stores the ZIP temporarily and sends a download link via WebSocket event
4. Auto-deletes the ZIP after 1 hour

### What to exclude from export

- **LLM API keys** — security risk, user already knows them
- **Password hashes** — no value to the user
- **Embedding vectors** — derived data, large, meaningless to humans
- **Knowledge chunks** — derived from documents, can be regenerated
- **Audit log** — internal operational data

### Effort estimate

**Medium — 3-4 days.**
- Day 1: Export service collecting data from all repositories
- Day 2: ZIP packaging, file inclusion, temporary storage
- Day 3: Endpoint, WebSocket events (export started/progress/ready/error), download endpoint
- Day 4: Frontend UI (button in user settings, progress indicator, download link)

No architectural changes needed — every repository already has `find_by_user` or equivalent
query methods. This is pure additive work.

---

## 3. Full Account Deletion (Right to Erasure)

**Question:** Can users fully delete their account with zero residual data?

### Current state

**Not possible.** The admin `DELETE /api/admin/users/{id}` endpoint only sets
`is_active = False` (soft deactivation). No data is removed. The `UserRepository`
has no hard-delete method at all.

### Proposed design

A new endpoint `DELETE /api/users/me` with confirmation flow:

1. **Confirmation step:** User must provide their password to confirm deletion
2. **Cascade deletion** in this order (respecting foreign key relationships):

```
Step 1: Delete all chat messages         (chat_messages where user_id)
Step 2: Delete all chat sessions         (chat_sessions where user_id)
Step 3: Delete all bookmarks             (bookmarks where user_id)
Step 4: Delete all artefact versions     (artefact_versions via artefact_ids)
Step 5: Delete all artefacts             (artefacts where user_id)
Step 6: Delete all knowledge chunks      (knowledge_chunks where user_id)
Step 7: Delete all knowledge documents   (knowledge_documents where user_id)
Step 8: Delete all knowledge libraries   (knowledge_libraries where user_id)
Step 9: Delete all memory entries        (memory_journal_entries where user_id)
Step 10: Delete all memory bodies        (memory_bodies where user_id)
Step 11: Delete all storage file records (storage_files where user_id)
Step 12: Delete upload directory         (rm -rf /data/uploads/{user_id}/)
Step 13: Delete avatar files             (all personas' profile_image files)
Step 14: Delete all personas             (personas where user_id)
Step 15: Delete integration configs      (user_integration_configs where user_id)
Step 16: Delete LLM credentials          (llm_user_credentials where user_id)
Step 17: Delete LLM curations/configs    (llm_model_curations, llm_user_model_configs)
Step 18: Delete projects                 (projects where user_id)
Step 19: Pseudonymise audit log          (replace user_id with "deleted-user-{hash}")
Step 20: Invalidate all sessions         (clear Redis tokens for user)
Step 21: Delete user record              (users where _id)
```

3. **WebSocket notification** before disconnecting: `account.deletion.complete`
4. **Audit:** A single pseudonymised audit entry: "User account deleted"

### Edge cases to handle

- Active WebSocket connections must be closed after deletion
- Redis session data and refresh tokens must be purged
- If deletion fails mid-cascade, it should be idempotent (can be retried)
- Admin users should not be able to delete themselves if they are the last admin

### Effort estimate

**Medium — 3-4 days.**
- Day 1: Hard-delete methods in UserRepository, cascade orchestration service
- Day 2: Endpoint with password confirmation, Redis cleanup, session invalidation
- Day 3: Edge cases (last admin check, idempotency, partial failure recovery)
- Day 4: Frontend UI (danger zone in settings, confirmation modal, feedback)

The cascade pattern already exists in the persona delete handler — this extends it
to the user level.

---

## 4. User-Based Encryption at Rest

**Question:** Can we encrypt chats, knowledge bases, system prompts, and memories
with a per-user key?

### Current state

Only LLM API keys are encrypted (Fernet, single server key). All other data is
stored in plaintext in MongoDB and on disk.

### Architecture options

#### Option A: Server-side per-user encryption (recommended)

Each user gets a unique Fernet key, derived from the server master key + user ID
(HKDF key derivation). Data is encrypted/decrypted transparently at the repository layer.

**Pros:**
- Transparent to the rest of the application
- No client-side key management
- Users don't lose data if they forget a passphrase
- Works with existing search and aggregation (decrypt at read time)

**Cons:**
- Server compromise exposes all keys (master key → all derived keys)
- Does not protect against a rogue admin with DB + server access

**Encrypted fields:**
| Collection | Fields to encrypt |
|-----------|------------------|
| `chat_messages` | `content`, `thinking` |
| `memory_journal_entries` | `content` |
| `memory_bodies` | `content` |
| `knowledge_documents` | `content` |
| `knowledge_chunks` | `text`, `heading_path`, `preroll_text` |
| `personas` | `system_prompt` |
| `storage_files` | on-disk file content |
| `artefacts` | `content` |
| `artefact_versions` | `content` |

**Impact on vector search:**
Knowledge chunk vectors (embeddings) are numerical and cannot be meaningfully
encrypted while remaining searchable. The vectors themselves do not contain
readable text — they are 768-dimensional float arrays. An attacker with only
the vectors cannot reconstruct the original text. The plaintext fields (`text`,
`heading_path`) would be encrypted.

#### Option B: Client-side encryption (E2EE)

The user holds their own key (derived from a passphrase). Data is encrypted in
the browser before being sent to the server.

**Pros:**
- True zero-knowledge — server never sees plaintext
- Strongest privacy guarantee

**Cons:**
- **Breaks server-side LLM inference entirely** — the server cannot read messages to send
  to the LLM. This is fundamentally incompatible with the current architecture where
  the backend orchestrates LLM calls.
- Knowledge base search would need to happen client-side
- Memory consolidation (server-side LLM job) would be impossible
- Lost passphrase = permanently lost data

**Verdict:** Option B is architecturally incompatible with Chatsune's design.
The backend must read user content to perform LLM inference, memory consolidation,
and knowledge retrieval.

### Recommended approach: Option A

Implement transparent field-level encryption at the repository layer using
per-user derived keys.

### Effort estimate

**Large — 8-12 days.**
- Days 1-2: Encryption service (HKDF key derivation, encrypt/decrypt helpers,
  field-level encryption decorator or mixin for repositories)
- Days 3-4: Migrate chat message and memory repositories to use encryption
- Days 5-6: Migrate knowledge, artefact, and persona repositories
- Days 7-8: Encrypt on-disk files (storage uploads, avatars)
- Days 9-10: Data migration tool for existing unencrypted data
- Days 11-12: Testing, edge cases, key rotation mechanism

**Key considerations:**
- Existing data must be migrated (encrypt-in-place migration script)
- A `encrypted: bool` flag on documents allows gradual migration
- Key rotation requires re-encrypting all user data (background job)
- Performance impact: ~1-2ms per encrypt/decrypt operation (Fernet is fast)
- No impact on MongoDB indexes (encrypted fields are not indexed, except for
  equality lookups which would need to use deterministic encryption or be removed)

---

## Effort Summary

| Feature | Effort | Complexity | Dependencies |
|---------|--------|-----------|-------------|
| 1. Granular deletion (chats + personas) | 1-2 days | Low | None |
| 2. Data export | 3-4 days | Medium | None |
| 3. Full account deletion | 3-4 days | Medium | Builds on #1 |
| 4. Per-user encryption at rest | 8-12 days | High | None, but benefits from #1-3 being done first |

**Recommended implementation order:** 1 → 3 → 2 → 4

Rationale:
- **#1 first** because it fills cascade gaps that #3 depends on
- **#3 before #2** because deletion is more commonly requested and higher regulatory priority
- **#2 after #3** because export needs to handle the same data set as deletion (shared understanding)
- **#4 last** because it touches every repository and benefits from all other work being stable

**Total estimate for all four features: 15-22 days of development.**
