# `session_seq` — Monotonic Message Ordering Migration

**Date:** 2026-05-17
**Status:** Approved (pre-implementation)
**Source brief:** [PRE-BRANCHING.md §(a)](../../PRE-BRANCHING.md) finding a-4
**Scope:** Replace `created_at` as the primary message-ordering key with a per-session monotonic integer counter. Prerequisite for branching (where messages need stable lineage independent of wall-clock collisions), and a correctness fix for the existing `delete_messages_after` `$gte` foot-gun.

---

## 1. Problem statement

Today every read and mutation of message ordering uses `created_at`, a
microsecond-resolution timestamp:

- `list_messages_tail` sorts by `created_at: 1`
  (`backend/modules/chat/_repository.py:918-925`).
- `delete_messages_after` (called from edit / regenerate) deletes by
  `created_at: {"$gte": target.created_at}`
  (`backend/modules/chat/_repository.py:1000-1006`). The `$gte` is
  deliberate — it deletes the target plus everything after — but it
  also means **two messages inserted within the same Python tick share
  a `created_at` and the wrong neighbour can be caught.** The tiebreak
  is `_id` (UUIDv4 = random), so it's nondeterministic which sibling
  goes.
- `edit_message_atomic` runs the same query
  (`backend/modules/chat/_repository.py:987-1017`).

For branching this is fatal: a branch is a sibling lineage off a parent
message, and the only way to express "messages 0..N belong to this
branch but not that branch" is with an ordered key that is *not* a
clock. We introduce `session_seq`, a per-session monotonic integer.

---

## 2. Out of scope

- Branching schema itself (a-9). This spec just makes ordering
  branch-safe.
- Cross-session ordering. `session_seq` is *per session*; the database
  primary key remains `_id`.
- `created_at` removal. We keep it — it stays useful for "when did this
  conversation happen" UI rendering and for the legacy backread filter
  that drops sub-second duplicates.

---

## 3. Data model

### 3.1 `ChatMessageDocument` — new field

`backend/modules/chat/_repository.py` — `save_message` writes:

```python
{
    "_id": ObjectId/UUID,
    "session_id": ...,
    "role": ...,
    "content": ...,
    "created_at": datetime,
    # NEW. Monotonic per session. 0-based, 1-based, doesn't matter as
    # long as it's monotonic and contiguous-on-insert (no gaps within
    # one session, except across deletions).
    "session_seq": int,
    ...
}
```

Index: compound `(session_id ASC, session_seq ASC)`, idempotent
`create_index` at startup. Existing indexes
(`session_id, created_at`) stay in place — `created_at` is still useful
for display and the legacy fallback read path.

### 3.2 Counter source — atomic increment on session document

`backend/modules/chat/_repository.py` — `ChatSessionDocument` gains:

```python
# Atomically incremented per insert. Default 0 for legacy docs;
# migration backfills the correct high-water mark (§5).
"last_message_seq": int = 0
```

`save_message` becomes a **two-step transaction-free atomic** sequence:

```python
result = await self._sessions.find_one_and_update(
    {"_id": session_id},
    {"$inc": {"last_message_seq": 1}},
    return_document=ReturnDocument.AFTER,
)
seq = result["last_message_seq"]
doc["session_seq"] = seq
await self._messages.insert_one(doc)
```

**Why not a MongoDB transaction across the two collections?** The
update returns the new value atomically; if the insert fails, we have
a "consumed but unused" seq on the session. That is acceptable —
gaps in `session_seq` are not a correctness problem (only monotonicity
matters), and `find_one_and_update` is cheap. The alternative — a
multi-doc transaction — is heavier and not justified for a counter.

**Race with concurrent inserts on the same session:**
`find_one_and_update` is atomic at the Mongo level even under RS0; two
concurrent saves on the same session get two distinct seqs in causal
order of the Mongo write. This is exactly the property we need to fix
the two-tab race symptoms in a-3 (pair ordering becomes correct even
when wall-clock collides).

---

## 4. Repository API changes

### 4.1 `list_messages_tail` — sort by `session_seq`

`backend/modules/chat/_repository.py:918-925`:

```python
# Before
.sort("created_at", 1)

# After
.sort("session_seq", 1)
```

`list_messages` (the legacy non-tail variant kept around for the
warning path from a-5) sorts the same way.

### 4.2 `delete_messages_from` — switch to `session_seq` (renamed from `delete_messages_after`)

```python
# Before
await self._messages.delete_many({
    "session_id": session_id,
    "created_at": {"$gte": target_msg["created_at"]},
})

# After
target_seq = target_msg["session_seq"]
await self._messages.delete_many({
    "session_id": session_id,
    "session_seq": {"$gte": target_seq},
})
```

Two-call-sites (edit_message_atomic and the regenerate path) both go
through this helper today, so the change is local. The rename to
`delete_messages_from` reflects the new inclusive semantics
(target + everything after) — the old `_after` name implied the
target was preserved, which never matched what callers actually
needed.

**Important:** the `last_message_seq` counter on the session document
is **not rewound** when we delete. A subsequent insert gets the
*next* seq value, creating a gap in the timeline. This is intentional
and matches the design — gaps are fine, monotonicity is the only
invariant.

### 4.3 `edit_message_atomic`

Already routes through `delete_messages_from`; no additional change.

### 4.4 New helper: `next_session_seq`

For the branching spec to clone-on-branch (next spec, not this one),
we expose:

```python
async def next_session_seq(self, session_id: str) -> int:
    """Reserve and return the next sequence number for a session."""
```

Implemented as the same `find_one_and_update` pattern. Not used in
this spec; declared here so the branching spec doesn't have to revisit
the file.

---

## 5. Migration

### 5.1 Migration script — `backend/migrations/0001_session_seq.py`

This is the first migration script in the repo. We bootstrap the
`backend/migrations/` directory per CLAUDE.md §Data-Model Migrations:

```python
"""Backfill session_seq on all existing message documents.

Idempotent: safe to re-run. Skips sessions whose
``last_message_seq`` is already non-zero AND whose message count
matches ``last_message_seq + gaps_tolerance``.
"""

async def run(db) -> None:
    sessions = db["chat_sessions"]
    messages = db["chat_messages"]

    async for session in sessions.find({}):
        session_id = session["_id"]
        if session.get("last_message_seq", 0) > 0:
            # Already migrated; verify roughly and skip.
            count = await messages.count_documents({"session_id": session_id})
            if count <= session["last_message_seq"]:
                continue
            # Counter exists but new untracked messages added — fall
            # through and re-backfill from scratch.

        cursor = messages.find(
            {"session_id": session_id}
        ).sort([("created_at", 1), ("_id", 1)])  # tiebreak _id

        seq = 0
        async for msg in cursor:
            seq += 1
            if msg.get("session_seq") == seq:
                continue
            await messages.update_one(
                {"_id": msg["_id"]},
                {"$set": {"session_seq": seq}},
            )

        await sessions.update_one(
            {"_id": session_id},
            {"$set": {"last_message_seq": seq}},
        )
```

### 5.2 Migration runner

Add `backend/migrations/__init__.py` with a `run_all(db)` function that
imports each `NNNN_*.py` module in order and calls its `run`. Wired
into `backend/main.py` at startup, **after** the index-creation block,
**before** the FastAPI app accepts requests. Logs the start and end of
each migration.

```python
@app.on_event("startup")
async def _migrate_on_startup():
    from backend.migrations import run_all
    await run_all(_db)
```

Idempotent re-runs are guaranteed by the script's own checks (§5.1).

### 5.3 Upgrade-path test (CLAUDE.md hard rule)

`tests/integration/test_session_seq_migration.py`:

- Build a fixture database with old-shape sessions: 3 sessions each
  with 5 messages, no `session_seq`, no `last_message_seq`.
- Run the migration once. Assert each session has
  `last_message_seq == 5` and each message has the expected
  `session_seq` (1..5 in `created_at` order).
- Re-run the migration. Assert nothing changes — confirm idempotency.
- Add a 6th message to one session **without** going through the
  repo (simulating a partial state — old code adds a doc but doesn't
  set seq). Re-run. Assert the new doc gets seq 6 and
  `last_message_seq` becomes 6.
- Insert a message via `save_message` (new code path). Assert the
  counter increments and the doc receives the right seq.

---

## 6. Backwards compatibility

- New field is **additive**; old documents without `session_seq` are
  readable. The migration backfills before the app accepts requests.
- The legacy `created_at` field is preserved and still written;
  display and the pair-selection backread can still use it where
  helpful (though §4 changes the *primary* ordering source).
- Pre-existing indexes on `(session_id, created_at)` stay — needed
  for the "list messages by time range" admin queries and for the
  `vision_descriptions_used` materialised view (if any).
- No frontend impact. Backend sorts before returning; frontend
  consumes ordered list as today.

---

## 7. Testing strategy

### 7.1 Unit tests

`tests/unit/test_repository_session_seq.py`:

- `save_message` increments the counter exactly once per insert.
- Two concurrent `save_message` calls on the same session get two
  distinct seqs (run with `asyncio.gather`).
- `list_messages_tail` returns sorted by `session_seq`.
- `delete_messages_from` removes the target and all higher-seq
  messages.
- `delete_messages_from` leaves `last_message_seq` unchanged
  (intentional gap).
- `next_session_seq` returns the expected value and increments the
  counter.

### 7.2 Migration test

§5.3 above.

### 7.3 Regression — two-tab race

Add to `tests/integration/test_chat_handlers.py` (or wherever the
existing handler tests live):

- Simulate the two-tab race scenario from a-3 by sending two
  `chat_send` requests in quick succession with same-tick `created_at`.
- Assert the resulting `list_messages_tail` order is the order of
  Mongo writes (causal), not the order of `_id` random tiebreak.

(This doesn't fix a-3 fully — that needs cancellation-await-save —
but it eliminates the *ordering* component of the race, which is the
part that breaks pair-matching.)

---

## 8. Implementation order

1. Add `session_seq: int = 0` and `last_message_seq: int = 0` defaults
   to the relevant Pydantic models. Backwards-compatible read per
   CLAUDE.md hard rule.
2. Update `save_message` with the find-one-and-update pattern. Add
   index. Build passes; existing tests still pass (because old
   messages have seq 0 and new messages get incremented seqs — pair
   matching gracefully handles either).
3. Switch `list_messages_tail` and `list_messages` to sort by
   `session_seq`. Run repo tests.
4. Rename `delete_messages_after` → `delete_messages_from` and switch
   the filter to `session_seq`. Run edit /
   regenerate handler tests.
5. Add `next_session_seq` helper.
6. Write migration script + runner + startup wiring.
7. Write upgrade-path test against a fixture old-shape DB.
8. Document the change in INSIGHTS.md (one INS entry).
9. `uv run pytest` passes.

---

## 9. Risk assessment

- **`find_one_and_update` overhead.** One extra round-trip per insert.
  Mongo RS0 local — sub-millisecond. Tolerable for chat-rate writes.
- **Counter gap on insert failure.** Acceptable; correctness only
  requires monotonicity. Logged at INFO when detected by the next
  insert? Not worth it — gaps are normal after deletes anyway.
- **Migration runtime on large databases.** Worst-case linear scan
  per session. The current product has a handful of users with a few
  hundred messages each; migration completes in seconds. Migration
  runs in an `@app.on_event("startup")` so first request after deploy
  waits a moment — acceptable for the alpha→beta cutover.
- **Index size.** Compound `(session_id, session_seq)` adds ~50% to
  the existing index footprint for `chat_messages`. Trivial in
  absolute terms for the current data volume.
