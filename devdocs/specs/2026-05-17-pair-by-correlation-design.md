# Pair Messages by `correlation_id` — Design Specification

**Date:** 2026-05-17
**Status:** Approved (pre-implementation)
**Source brief:** [PRE-BRANCHING.md §(a)](../../PRE-BRANCHING.md) findings a-2, a-3, a-10
**Scope:** Replace position-based pair matching in `select_message_pairs`
with `correlation_id`-based pairing. Solves a-2 (orphan user dropped
silently), a-3 (two-tab race poisons history), and a-10 (aborted user
pollution) with a single coherent change. Last structural prerequisite
before branching — under the tree model "positional adjacency" no
longer expresses lineage, but a `correlation_id` invariant carries
through cleanly.

---

## 1. Problem statement

Today the orchestrator pairs user and assistant messages by **position
in the chronological list**:

```python
# backend/modules/chat/_context.py:54
while i + 1 < len(messages):
    if messages[i]["role"] == "user" and messages[i + 1]["role"] == "assistant":
        pairs.append((messages[i], messages[i + 1]))
        i += 2
    else:
        i += 1
```

Three known consequences:

- **a-2:** `_filter_usable_history` drops aborted assistants but leaves
  the sibling user. The pair-builder then sees `[user, user, assistant]`,
  advances `i += 1` on non-alternation, and silently never emits the
  orphan user. The model has no record the user said anything on that
  turn.
- **a-3 (semantic half):** the two-tab race writes user_B *between*
  user_A and the cancelled assistant-for-A. With `session_seq` the
  order is now deterministic, but the pair-builder still pairs `user_B`
  with `assistant-for-A` (since they're adjacent), so the model
  receives a reply addressed to the wrong question.
- **a-10:** orphan user messages persist after compaction's
  `_filter_usable_history` strips the aborted assistant; the orphan
  pollutes pair-matching and can dangle a `tail_start_message_id`.

`correlation_id` is already on every user message and every assistant
message that flows through `save_fn` — except the **assistant write
path currently drops it**, and **imported documents have
`correlation_id: None` by design**. Both are fixable.

Once assistant docs carry the correct `correlation_id`, pairing
becomes a key lookup that is robust against:
- aborted / cancelled / refused / error assistants (filtered before
  the pair set is built),
- write-order skew (race-poisoned timelines re-pair correctly
  regardless of intervening writes),
- branching (a branch clone preserves correlation_ids and pairing
  works without changes).

---

## 2. Out of scope

- Branching schema itself (a-9).
- `_filter_usable_history` reordering of compaction tail anchor lookup
  vs filter pass (subtle, separate fix).
- Frontend changes — the pair-builder is backend-only.
- Per-adapter behavioural changes (untouched).

---

## 3. Data model

### 3.1 Existing fields used

Every message document already carries:

```python
{
    "_id": str,
    "session_id": str,
    "role": Literal["user", "assistant"],
    "correlation_id": str | None,   # populated for user msgs; None today on assistants
    "status": Literal["completed", "aborted", "refused"],
    "session_seq": int,             # from the 2026-05-17-session-seq spec
    "created_at": datetime,
    ...
}
```

### 3.2 No schema change required

`correlation_id` is already on the wire. The fix is:

1. **Forward-fix:** make the assistant write path forward the
   correlation_id it already has in closure scope (orchestrator
   `save_fn`, line 1241–1287).
2. **Backfill migration:** infer the correlation_id of legacy
   assistant docs by reading the adjacent user's correlation_id.
3. **Imported docs:** assign synthetic correlation_ids during the
   same migration so they're pair-able.

### 3.3 Status semantics — single source of truth

We standardise on the existing `status` field for the "do not replay"
gate. Values to be filtered out of pair selection:

| Status | Meaning | Filter behaviour |
|---|---|---|
| `"completed"` | Normal assistant reply | Keep |
| `"aborted"` | Cancelled mid-stream (user clicked stop, two-tab race, etc.) | Drop pair |
| `"refused"` | Provider refusal | Drop pair |

The two-tab race case becomes another `"aborted"` — no new status
value needed. The race is solved by the *pairing logic*, not by a
new tag.

---

## 4. Forward-fix: assistant write path

### 4.1 Orchestrator `save_fn`

`backend/modules/chat/_orchestrator.py:1241–1287`. The closure already
captures `correlation_id` (used at line 1284 when submitting the
title-generation job). Add it to the `save_message` call:

```python
doc = await repo.save_message(
    session_id,
    role="assistant",
    content=content,
    token_count=token_count,
    thinking=thinking,
    thinking_blocks=thinking_blocks,
    usage=usage,
    events=events,
    refusal_text=refusal_text,
    status=status,
    correlation_id=correlation_id,   # NEW
)
```

That single line is the forward fix. Every assistant doc written from
this point forward carries the matching user's correlation_id.

### 4.2 Audit other save_message call sites

`grep -n "save_message" backend/` confirms only two production call
sites:
- `_handlers_ws.py:393` — user message, already forwards `correlation_id`.
- `_orchestrator.py:1251` — assistant message via `save_fn`, fix above.

Edit/regenerate flows route through `save_fn`, so a single change covers
all assistant writes.

### 4.3 `user_id` on assistant docs

Currently `save_fn` does not pass `user_id` either; the closure has it.
Add `user_id=user_id` alongside `correlation_id` for consistency — the
sparse index `(user_id, correlation_id)` (created at line 274) is used
by the retract flow and works better with `user_id` populated. Strictly
optional, but cheap and orthogonal.

---

## 5. Migration — `0002_assistant_correlation_id.py`

### 5.1 Scope

Two cohorts of documents need backfill:

**A. Legacy assistant docs** written before §4.1 lands. Their
`correlation_id` is `None`. We infer the correct value from the
adjacent user message — the one immediately preceding by
`session_seq`.

**B. Imported assistant + user docs** from ChatGPT imports. Both have
`correlation_id: None` by design (`_repository.py:381`). They have
no preceding context to infer from, so we assign synthetic ids of
the shape `f"imported-{session_id}-{seq}"`. The same id is shared
across one user + one assistant for each turn, giving the pair-builder
a valid key.

### 5.2 Algorithm

```python
"""Backfill correlation_id on assistant docs and imported messages."""

async def run(db) -> None:
    sessions = db["chat_sessions"]
    messages = db["chat_messages"]

    async for session in sessions.find({}):
        session_id = session["_id"]
        is_imported = bool(session.get("imported_from"))

        cursor = messages.find(
            {"session_id": session_id}
        ).sort([("session_seq", 1), ("created_at", 1), ("_id", 1)])
        docs = await cursor.to_list(length=None)

        if is_imported:
            # All correlation_ids are None by construction.
            # Walk pairs and assign synthetic ids.
            await _backfill_imported(messages, session_id, docs)
        else:
            await _backfill_legacy(messages, docs)


async def _backfill_legacy(messages, docs):
    """For each assistant doc with correlation_id=None, copy the
    correlation_id of the immediately-preceding user doc."""
    last_user_cid: str | None = None
    for d in docs:
        if d["role"] == "user":
            last_user_cid = d.get("correlation_id")
            continue
        if d["role"] != "assistant":
            continue
        if d.get("correlation_id") is not None:
            continue
        if last_user_cid is None:
            # No preceding user — synthetic orphan id so the doc is
            # representable but won't pair. Rare; would only happen
            # if a session somehow started with an assistant doc.
            synthetic = f"orphan-{d['_id']}"
            await messages.update_one(
                {"_id": d["_id"]}, {"$set": {"correlation_id": synthetic}},
            )
            continue
        await messages.update_one(
            {"_id": d["_id"]}, {"$set": {"correlation_id": last_user_cid}},
        )


async def _backfill_imported(messages, session_id, docs):
    """Pair imported user + assistant docs by adjacency and assign
    synthetic correlation_ids."""
    pair_idx = 0
    pending_user: dict | None = None
    for d in docs:
        if d.get("correlation_id") is not None:
            # Migration is idempotent — already done.
            continue
        if d["role"] == "user":
            if pending_user is not None:
                # Two users in a row — assign orphan id to the first.
                synthetic = f"imported-{session_id}-orphan-{pair_idx}"
                pair_idx += 1
                await messages.update_one(
                    {"_id": pending_user["_id"]},
                    {"$set": {"correlation_id": synthetic}},
                )
            pending_user = d
            continue
        if d["role"] == "assistant":
            synthetic = f"imported-{session_id}-{pair_idx}"
            pair_idx += 1
            if pending_user is not None:
                await messages.update_one(
                    {"_id": pending_user["_id"]},
                    {"$set": {"correlation_id": synthetic}},
                )
                pending_user = None
            await messages.update_one(
                {"_id": d["_id"]}, {"$set": {"correlation_id": synthetic}},
            )
    # Trailing user without assistant — synthetic orphan id.
    if pending_user is not None:
        synthetic = f"imported-{session_id}-orphan-{pair_idx}"
        await messages.update_one(
            {"_id": pending_user["_id"]},
            {"$set": {"correlation_id": synthetic}},
        )
```

### 5.3 Idempotency

The migration checks `correlation_id is not None` before writing.
Re-running is a no-op for already-migrated docs. New legacy assistant
docs written between this migration and the §4.1 forward-fix being
deployed get picked up on the next startup.

### 5.4 Index

Already exists: sparse `(user_id, correlation_id)` index at
`_repository.py:271-275`. Sparse means it only includes docs with a
non-null `correlation_id` — once the migration runs, the index
becomes fully populated for all docs. No change required.

We do **not** add a `(session_id, correlation_id)` index. The
pair-builder operates on an already-loaded `list_messages_tail`
result; no per-session correlation_id queries.

---

## 6. Pair-builder rewrite — `select_message_pairs`

### 6.1 New algorithm

```python
def select_message_pairs(
    messages: list[dict],
    available_tokens: int,
) -> tuple[list[dict], int]:
    """Select message pairs by correlation_id within budget.

    Pairs a user message with the assistant message that shares its
    correlation_id. Assistant messages with status != "completed"
    cause their pair to be dropped entirely (the user message goes
    too — the turn produced no usable reply).

    Returns (selected_messages_in_chronological_order, total_tokens).
    """
    # 1. Index by correlation_id.
    by_corr: dict[str, dict] = {}  # cid -> {"user": doc, "assistant": doc}
    user_order: list[dict] = []  # user messages in original order

    for m in messages:
        cid = m.get("correlation_id")
        if not cid:
            # Defensive: no migration backfill happened, or a
            # synthetic-orphan id was assigned. Skip — pair-matching
            # requires a key.
            continue
        slot = by_corr.setdefault(cid, {})
        if m["role"] == "user":
            slot["user"] = m
            user_order.append(m)
        elif m["role"] == "assistant":
            slot["assistant"] = m

    # 2. Build complete pairs, preserve original ordering.
    pairs: list[tuple[dict, dict]] = []
    for user_msg in user_order:
        cid = user_msg["correlation_id"]
        slot = by_corr[cid]
        asst = slot.get("assistant")
        if asst is None:
            # Orphan user (cancelled before any reply, or split
            # across import) — skip.
            continue
        if asst.get("status") != "completed":
            # Aborted, refused, errored — drop the whole pair. The
            # user message would otherwise have no matching reply,
            # which breaks every adapter's prompt contract.
            continue
        pairs.append((user_msg, asst))

    # 3. Newest-first budget selection (unchanged from today).
    selected_pairs: list[tuple[dict, dict]] = []
    total_tokens = 0
    for pair in reversed(pairs):
        pair_tokens = pair[0]["token_count"] + pair[1]["token_count"]
        if total_tokens + pair_tokens > available_tokens:
            continue
        selected_pairs.append(pair)
        total_tokens += pair_tokens
    selected_pairs.reverse()

    result: list[dict] = []
    for u, a in selected_pairs:
        result.append(u)
        result.append(a)
    return result, total_tokens
```

### 6.2 What the old filter does, and what now changes

Today `_filter_usable_history` lives at `_orchestrator.py:77-83` and
drops `status in {"aborted", "refused"}` assistants — leaving the
sibling user behind. That's the root of a-2.

With the new pair-builder, **`_filter_usable_history` becomes a
no-op for status-based filtering** — the pair-builder itself handles
status. We keep `_filter_usable_history` as a function (callers
still invoke it) but it can be simplified to a pass-through, or
optionally extended later for unrelated filters (e.g. deleted_at).

Leave it as pass-through for this spec, with a comment pointing to
`select_message_pairs` for status semantics. Removing the call site
is out of scope here — it would mean editing every regression test.

### 6.3 Behavioural changes — explicit

- **a-2 fix:** user message without matching completed assistant
  is dropped. Same end-state as today, but explicit (no silent
  pair-builder skip).
- **a-3 fix:** two-tab race re-pairs correctly. Even if the write
  order is `user_A → user_B → aborted-asst-for-A` (which session_seq
  now makes deterministic), the pair-builder pairs user_B with
  whichever completed assistant carries user_B's correlation_id.
  user_A's pair has an aborted assistant, so the pair is dropped.
- **a-10 fix:** the aborted user message is no longer kept around
  by the pair-builder. Compaction's tail anchor logic is unaffected
  because it runs on the unfiltered `history_docs` before the pair
  selection.

### 6.4 What if all assistants are aborted?

Pair set is empty. `select_message_pairs` returns `([], 0)`. The
orchestrator then sends only `system + new user message` to the LLM
— exactly what happens today with a fresh session. The model has no
prior context but the user's most recent message goes through.

### 6.5 What if `correlation_id` is missing on a doc?

After the migration runs, every doc has one. Defensive `continue`
in the loop covers the edge case where new code somehow writes a
doc without it (would be a bug to investigate, but doesn't crash
the pair-builder).

---

## 7. Tests

### 7.1 Unit tests — `tests/test_context_pair_by_correlation.py` (new)

- **Basic pairing:** three completed turns → all three pairs returned
  in order.
- **Budget cap:** budget fits only the latest two pairs → oldest
  pair dropped.
- **Aborted assistant:** pair with `status="aborted"` excluded; other
  pairs preserved.
- **Refused assistant:** same.
- **Orphan user (no assistant matching cid):** dropped silently.
- **Two-tab race scenario:** docs in order
  `user_A(cid=A) → user_B(cid=B) → aborted-asst(cid=A) → completed-asst(cid=B)`
  pair-builder returns `[user_B, completed-asst-for-B]`.
- **Missing correlation_id (defensive):** doc skipped without error.
- **Same correlation_id appears twice for the same role:** last-write
  wins on the slot (regenerate path overwrites). Verified by setting
  two assistants with the same cid; pair uses the last one.

### 7.2 Integration test — `tests/migrations/test_correlation_id_backfill.py` (new)

- **Legacy session:** fixture with 3 user docs (each with cid) and 3
  assistant docs (all cid=None). Run migration. Each assistant gets
  the adjacent user's cid.
- **Imported session:** fixture with `imported_from` set and 4 docs
  (user/asst/user/asst), all `cid=None`. Run migration. Each pair
  gets a synthetic `imported-{sid}-{idx}` id.
- **Orphan user in legacy:** fixture with `user → assistant → user`
  (cancelled before reply). Last user is orphan. Migration doesn't
  touch it (cid stays None) — pair-builder will skip it gracefully.
- **Idempotency:** run migration twice. Second run is a no-op.
- **Two users in a row in imported:** edge case from broken imports.
  First user gets `imported-{sid}-orphan-{idx}` synthetic id; second
  gets `imported-{sid}-{pair_idx}` paired with the following
  assistant.

### 7.3 Regression — existing pair-builder tests

Existing tests in `tests/test_context_*` (search with `rg`) that
assert position-based behaviour need updates. A clean rewrite of
those test files is preferred over migration-style retrofitting.
The pair-builder's interface is unchanged
(`select_message_pairs(messages, available_tokens) -> tuple`); only
the algorithm changes.

### 7.4 End-to-end smoke

`tests/test_chat_repo_phase2.py` or wherever the integration-style
chat flow tests live — verify that a completed `chat.send` produces
a doc with `correlation_id == user_correlation_id` after the
forward-fix lands. One assertion line.

---

## 8. Backwards compatibility

- Forward-fix is **additive** — old code paths that called `save_fn`
  without `correlation_id` still work (the kwarg defaults to `None`),
  but no one calls `save_fn` directly except the orchestrator's own
  inner code which we control.
- Migration **runs at startup** (chained into `run_all` from
  spec 2026-05-17-session-seq). First request after deploy waits a
  moment — acceptable for the alpha→beta cutover.
- Existing tests that build synthetic fixture docs without
  `correlation_id` will see them skipped by the new pair-builder. Tests
  are updated as part of §7.

---

## 9. Implementation order

1. Forward-fix: orchestrator `save_fn` passes `correlation_id` and
   `user_id` to `repo.save_message`. One-file change. Existing tests
   pass.
2. Migration `0002_assistant_correlation_id.py` with legacy + imported
   backfill paths. Add to `run_all` discovery (already automatic via
   `NNNN_*.py` regex from the previous spec).
3. Rewrite `select_message_pairs` in `backend/modules/chat/_context.py`.
4. Reduce `_filter_usable_history` (in `_orchestrator.py:77-83`) to a
   pass-through with a comment pointing at the pair-builder for status
   semantics. Don't remove the call — would touch too many tests.
5. Update existing pair-builder tests; add new test files per §7.
6. Run the migration test against a hand-crafted fixture DB
   (CLAUDE.md hard rule).
7. INSIGHTS.md entry (INS-048).
8. Full `uv run pytest` clean.

---

## 10. Risk assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Migration sets wrong cid on aborted-asst-during-import (rare) | Low | Aborted asst gets paired-and-dropped — same end state | Accept |
| Two assistants share a cid (regenerate replaced the old one but the migration sees both) | Low | Last-write-wins on the slot — works correctly | Test 7.1 covers it |
| New code writes a doc without cid | Low | Pair-builder skips silently | Add a logged warning if observed in production |
| `_filter_usable_history` pass-through plus future filter (e.g. deleted_at) | Low | Filter could re-introduce the old bug if it drops by role | Comment explicitly: "do NOT drop by role; pair-builder handles status" |
| Imported session with already-paired correlation_ids (a non-default importer set them) | Very low | Migration skips them — pair-builder works | Test 7.2 idempotency case |
| Concurrent migration + new save_message | None | Migration only writes when cid is None; new writes set cid | n/a |

---

## 11. What this unblocks

- **Branching (a-9):** clone-on-branch preserves correlation_ids,
  so the pair-builder works in branches without any changes. The
  "positional adjacency breaks under tree model" concern from
  PRE-BRANCHING §(d) item 2 is resolved.
- **Pair-by-correlation makes b-1/b-2/b-3 (reasoning + tool replay)
  more robust:** the assistant doc pulled into the prompt is
  *guaranteed* to be the one that answered the matched user message,
  not a positional neighbour. Reasoning-trace replay becomes correct
  even under race conditions.
- **a-10 closed without separate work.**
