# Branching — Design Specification

**Date:** 2026-05-17
**Status:** Approved (pre-implementation)
**Source brief:** [PRE-BRANCHING.md](../../PRE-BRANCHING.md) §branching model + finding a-9, plus UX decisions taken in-session 2026-05-17 with Chris.
**Scope:** Flagship feature for Chatsune v0.2.0. Users can fork a conversation at any past point into an independent new session ("branch"). Branches are full session-document clones, not lightweight pointers — clean compose with existing compaction, memory, tool-call replay, and pair-by-correlation machinery.

---

## 1. Vision

A branch is "a new chat that starts where an existing chat left off at message N". It is **a normal session document with its own _id, name, and lifecycle**. It carries a clone of all messages up to and including the fork point, with the same correlation_ids (so pair-matching and reasoning replay continue to work) but new `_id` values (so DOM rendering, pillContents caches, and storage references don't collide).

After creation, a branch is **fully independent** — renaming, deleting, exporting, or compacting the parent has no effect on it, and vice versa. There is **no UI badge or banner indicating "you're in a branch"** — that's by design. Each branch stands on its own.

Branches address three needs the product currently does not serve:

- "Try an alternative response without losing the original" (regenerate-but-keep)
- "Edit an old message and explore from there without rewriting history" (edit-with-preservation)
- "Branch the conversation at any point so I can A/B compare angles" (explicit exploration)

---

## 2. Behavioural patterns — 4 trigger cases

| # | Trigger | Position | Result | Dialog? |
|---|---|---|---|---|
| 1 | Edit user message + "save and resend" | **LAST** user msg | Choose: in-place regenerate OR new branch | Yes — *"Antwort ersetzen oder neuer Branch?"* |
| 2 | Edit user message + "save and resend" | EARLIER user msg | Force new branch (in-place would invalidate later messages) | Name dialog only |
| 3 | "Branch" button on assistant message | Any | Force new branch with same user message; new inference for the assistant turn | Name dialog only |
| 4a | "Regenerate" button on assistant message | **LAST** assistant | In-place regenerate (overwrite); no branch | None |
| 4b | "Regenerate" button on assistant message | EARLIER assistant | Force new branch (Re-labeled **"Branch & Regenerate"** to communicate this) | Name dialog only |

### 2.1 Why the labels matter

On the **last** assistant message both `[Regenerate]` and `[Branch]` are visible and distinct. On any **non-last** assistant message the regenerate button is re-labeled to `[Branch & Regenerate]` and the separate `[Branch]` button stays, offering two distinct actions:

- **[Branch & Regenerate]** — clone up to and including the user msg before this assistant, then run a fresh inference. Endpoint state in the new branch: the new alternative assistant reply is already there, ready for the user to continue.
- **[Branch]** — clone up to and including this assistant message verbatim. Endpoint state in the new branch: user can type the next message themselves; the existing assistant reply is preserved in the branch.

The duality survives the redundancy concern because the user intent is different (immediate alternative vs preserve-and-continue).

---

## 3. Fork-point semantics

### 3.1 Where the fork happens

Let `M_N` be the message the user is acting on. The fork point is **the latest assistant message in chronological order that has a strictly lower `session_seq` than `M_N`**, or the session start if no such assistant exists. The branch's history contains all messages up to and including the fork-point message; everything from `M_N` onward is **new** in the branch.

Concrete examples:

- Action on user msg `M_5` (any case 1/2/3 on a user) → fork point is `M_4` (the assistant just before). Branch shares M_1..M_4; `M_5'` in the branch is the edited (or unchanged) user msg; M_6' is a new inference.
- Action on assistant msg `M_4` (case 3 or 4b) → fork point is `M_2` (the assistant before the user msg that produced `M_4`). Branch shares M_1..M_2; `M_3'` is a verbatim clone of M_3 (the prior user); `M_4'` is a new alternative inference (or, for case 3 with just-Branch-no-regenerate, a verbatim clone of `M_4`).

This rule guarantees:
- Pair-matching in the branch is well-formed (every user has its matched assistant in the cloned tail).
- The fork point is always an assistant-completed turn (or the session start), never mid-pair.

### 3.2 Compaction checkpoints across the fork

Per Chris's PRE-BRANCHING answer to Q3 and Q4: **clone all compaction_checkpoints up to the fork point**. If the user branches between checkpoints 2 and 3, the cloned branch carries checkpoints 1 and 2 plus the post-checkpoint-2 tail up to the fork. No checkpoint past the fork is copied (none exist yet by definition of "up to fork").

---

## 4. Data model

### 4.1 `ChatSessionDocument` — new field

`backend/modules/chat/_models.py`:

```python
class ChatSessionDocument(BaseModel):
    # ... existing fields ...

    # Lineage pointer for branches. ``None`` for top-level sessions
    # (the common case). Set on clone-on-branch. See spec
    # ``devdocs/specs/2026-05-17-branching-design.md``.
    forked_from: ForkedFromPointer | None = None


class ForkedFromPointer(BaseModel):
    """Records where this session was branched off from. Informational
    only — the branch is fully independent after creation. Used by
    future analytics / 'show branches' features; not consulted by the
    inference path."""

    session_id: str       # parent session _id at clone time
    message_id: str       # fork-point message _id in the parent
    session_seq: int      # parent's session_seq at the fork point
    created_at: datetime  # when the branch was forked off
```

**Backwards-compat (CLAUDE.md hard rule):** default `None`. Existing sessions deserialise unchanged. No migration script.

### 4.2 Why not a deeper tree structure on disk

We considered `parent_id` + `branch_id` columns with branches sharing a session document. Rejected (PRE-BRANCHING answer to Q1): clone-on-branch keeps storage cost low-priority and composes cleanly with everything we already built. Each branch is a normal `ChatSessionDocument` and a normal set of `ChatMessageDocument`s. No new query paths, no special routing.

### 4.3 What gets cloned

Per the PRE-BRANCHING decisions:

| Item | Cloned? | Notes |
|---|---|---|
| `ChatSessionDocument` itself | Yes | New `_id`, new `created_at`, `forked_from` set, name user-supplied |
| Messages up to fork point | Yes | New `_id`s, **same `correlation_id`s**, new `created_at` (clone time), new `session_seq` (re-stamped 1..N) |
| `compaction_checkpoints` array on the session | Yes | Up to fork point only |
| `messagePillContents` cache (frontend) | Clone (not share) | Per d-15 documented invariant |
| Attachments (`attachment_refs`) on messages | Reference-clone (point to same storage) | Becomes "dead link" if the user later deletes the original attachment via parent. **Accepted limitation** (Chris's answer to Q1 in PRE-BRANCHING). |
| Artefacts (`artefact_refs`) on messages | Reference-clone | Same dead-link caveat |
| Generated images (`image_refs`) on messages | Reference-clone | Same |
| Tool-call timeline events on assistant docs | Cloned verbatim **with a "not replayed — clone" indicator** | See §4.4. Per Chris's answer to Q5: replay the recorded tool result (option a), do NOT re-execute (option b). |
| `last_message_seq` on session | Re-computed | Set to the number of cloned messages |
| `extras` on session | Cloned (full snapshot of parent's extras at clone time) | Reasoning mode, tools_enabled, replay_tool_history — all copied |
| User_id, persona_id, project_id | Copied | Branch belongs to the same user/persona/project |
| `pinned` | Reset to `False` | Branch starts unpinned regardless of parent state |
| `state` | Reset to `"idle"` | Branch starts idle even if parent is streaming |

### 4.4 The "not replayed — clone" indicator

Per Q5, cloned tool-call events do not trigger re-execution (which would duplicate side effects like `write_journal_entry`). The recorded `result_content` from the parent is preserved on the cloned event. For the user's awareness we add a flag:

```python
# On each cloned tool-call event in the cloned message's ``events`` array:
{
    "kind": "tool_call",
    # ... existing fields ...
    "cloned_from_branch": True,  # NEW. Set only at clone time.
}
```

Frontend rendering (frontend tool-call pill): when this flag is true, show a small subtitle "Tool nicht erneut ausgeführt — geklont aus Parent". The pill still renders the prior result so the conversation reads coherently.

Same logic for `TimelineEntryArtefact`, `TimelineEntryImage`, `TimelineEntryKnowledgeSearch`, `TimelineEntryWebSearch` — they all get a `cloned_from_branch: bool` field that defaults to `False`.

---

## 5. Backend — API and clone job

### 5.1 Endpoint

```
POST /api/chat/sessions/{parent_session_id}/branch
Body: { "fork_message_id": str | None, "name": str }
Response 201: ChatSessionDto (the new branch's full doc)
Response 400: invalid fork_message_id (not in parent), invalid name
Response 404: parent session not found
Response 409: compaction lock held on parent — try again
```

`fork_message_id` is the **fork-point** message id — always an assistant
message id, or `null` (None on the wire) when the branch is from the
very start of the session (e.g. user edits the first user message into
a branch). The frontend computes it from the action context (which
message the user clicked + which user message belongs to it).

### 5.2 Pre-flight checks

Before clone work begins:

1. Ownership check: `parent_session.user_id == user_id` (else 404).
2. Compaction lock check: `compaction:lock:{parent_session_id}` not held (else 409 with retry advice).
3. Name validation: non-empty after strip, ≤ 200 chars (matches existing session-title validation).
4. Fork-point exists in parent (else 400 with `fork_message_not_found`).
5. Fork-point is assistant role or session-start (else 400 with `fork_message_invalid` — defensive, frontend should never send a user message here).

### 5.3 Clone procedure (synchronous, transactional)

Per Chris's "sync with loader" UX:

```python
async def clone_session_at(
    repo: ChatRepository,
    parent_session_id: str,
    fork_message_id: str,
    new_name: str,
    user_id: str,
) -> dict:
    """Clone-on-branch. Synchronous; returns the new session document."""

    # 1. Load parent and fork-point under a Mongo transaction so a
    #    parallel compaction can't slip in.
    async with await client.start_session() as session, session.start_transaction():
        parent = await repo._sessions.find_one(
            {"_id": parent_session_id, "user_id": user_id},
            session=session,
        )
        if not parent:
            raise NotFoundError(...)

        fork_msg = await repo._messages.find_one(
            {"_id": fork_message_id, "session_id": parent_session_id},
            session=session,
        )
        if not fork_msg or fork_msg["role"] != "assistant":
            raise ValueError("fork_message_invalid")

        # 2. Pull all messages up to AND INCLUDING the fork point.
        cursor = repo._messages.find(
            {"session_id": parent_session_id,
             "session_seq": {"$lte": fork_msg["session_seq"]}},
            session=session,
        ).sort("session_seq", 1)
        parent_msgs = await cursor.to_list(length=None)

        # 3. Build the new session document.
        new_session_id = str(uuid4())
        now = datetime.now(UTC)
        new_session = {
            "_id": new_session_id,
            "user_id": parent["user_id"],
            "persona_id": parent["persona_id"],
            "project_id": parent.get("project_id"),
            "title": new_name,
            "state": "idle",
            "pinned": False,
            "extras": parent.get("extras"),
            "compaction_checkpoints": [
                cp for cp in (parent.get("compaction_checkpoints") or [])
                if cp["tail_start_message_id"] in {m["_id"] for m in parent_msgs}
            ],
            "last_message_seq": len(parent_msgs),
            "forked_from": {
                "session_id": parent_session_id,
                "message_id": fork_message_id,
                "session_seq": fork_msg["session_seq"],
                "created_at": now,
            },
            "created_at": now,
            "updated_at": now,
        }
        await repo._sessions.insert_one(new_session, session=session)

        # 4. Clone each message: new _id, same correlation_id,
        #    re-stamped session_seq (1..N), cloned timeline events
        #    flagged as cloned_from_branch.
        new_msgs = []
        for idx, m in enumerate(parent_msgs, start=1):
            new_msg = {**m}
            new_msg["_id"] = str(uuid4())
            new_msg["session_id"] = new_session_id
            new_msg["session_seq"] = idx
            new_msg["created_at"] = now
            # cloned_from_branch flag on tool events
            if isinstance(new_msg.get("events"), list):
                new_msg["events"] = [
                    {**ev, "cloned_from_branch": True}
                    if isinstance(ev, dict)
                    else ev
                    for ev in new_msg["events"]
                ]
            new_msgs.append(new_msg)
        if new_msgs:
            await repo._messages.insert_many(new_msgs, session=session)

        # 5. Compaction checkpoints whose tail_start_message_id pointed
        #    into the parent need re-mapping to the new branch's _ids.
        if new_session["compaction_checkpoints"]:
            id_map = {old["_id"]: new_msgs[idx]["_id"]
                      for idx, old in enumerate(parent_msgs)}
            new_session["compaction_checkpoints"] = [
                {**cp, "tail_start_message_id": id_map[cp["tail_start_message_id"]]}
                for cp in new_session["compaction_checkpoints"]
            ]
            await repo._sessions.update_one(
                {"_id": new_session_id},
                {"$set": {"compaction_checkpoints": new_session["compaction_checkpoints"]}},
                session=session,
            )

        return new_session
```

**Why transactional:** the multi-doc clone must be atomic. A parallel compaction on the parent could pull the rug from under step 4 if we read messages without a transaction. RS0 supports multi-doc transactions, so we use them.

### 5.4 Response and follow-up events

After successful clone:

- Emit `Topics.CHAT_SESSION_CREATED` for the new session so other tabs see it in their sidebar.
- Return the full `ChatSessionDto` to the caller.

For the case 1 "Antwort ersetzen oder neuer Branch?" → "neuer Branch" + the case 2 / case 3 / case 4b patterns where a new inference must also run: the **frontend** receives the response, switches to the new session, then issues a normal `chat.send` (case 1 + 2 with new user msg content) or `chat.regenerate` (case 4b) against the branch session_id. The branch endpoint itself does NOT run inference — that's the caller's job. Keeps the endpoint side-effect-free in inference terms.

### 5.5 Error handling

- DB error during transaction: roll back, return 500 with structured `{"error_code": "clone_failed"}`. Frontend shows a toast and stays in the parent session.
- Compaction lock held: 409 + suggested retry-after.
- Fork point not assistant: 400 (defensive; should not be reachable via UI).

---

## 6. Frontend — UI flows

### 6.1 Action-bar buttons on assistant message

`frontend/src/features/chat/MessageList.tsx` (or wherever the existing per-message actions live):

**Existing buttons** stay: Copy, etc.

**New / re-labelled buttons** (assistant message only):

| Button | Visible when | Action |
|---|---|---|
| Regenerate / "Regenerate" | This is the LAST assistant message | In-place regenerate via existing flow (delete this message, rerun on previous user) |
| Regenerate / "Branch & Regenerate" | This is NOT the LAST assistant message | Open name dialog → on confirm: POST /branch → switch to branch → trigger regenerate |
| Branch / "Branch" | Always on assistant messages | Open name dialog → on confirm: POST /branch → switch to branch (no inference) |

A simple `useIsLastAssistantMessage(messageId)` hook + conditional label.

### 6.2 Edit + "save and resend" flow

Lives on **user** messages. Existing edit flow:

1. User edits a user message inline.
2. User clicks "Save and resend".
3. Frontend computes: is this the LAST user message in this session?

   - **Yes (case 1):** open dialog **"Antwort ersetzen oder neuer Branch?"** with two primary buttons:
     - `[Antwort ersetzen]` — existing in-place flow (delete subsequent messages via `delete_messages_from`, save edited content via `edit_message_atomic`, trigger inference).
     - `[Neuer Branch]` — open name dialog → POST /branch with `fork_message_id` = the **assistant before this user msg** (i.e., the assistant at `current_user.session_seq - 1`, or session-start if user msg was the first message) → switch to branch → trigger `chat.send` against branch with the edited content (functions as the branch's first user message after the cloned history).

   - **No (case 2):** open name dialog directly (no "replace" option exists) → POST /branch with `fork_message_id` = the assistant immediately before this user → switch to branch → trigger `chat.send` against branch with edited content.

### 6.3 Name dialog component

`frontend/src/features/chat/branching/BranchNameDialog.tsx` (new):

- Modal centred, dismissable via Escape / overlay click → no branch created.
- Title: "Neuen Branch erstellen"
- Body: input field, pre-filled with `"${parentTitle} (Variante ${nextVariantIndex})"`.
  - `nextVariantIndex` = `1` if no sibling branches exist, else `(max sibling variant index) + 1`. Sidebar already loads the user's sessions; the dialog walks them to compute it.
- Primary action: `[Branch erstellen]` (enabled when input non-empty after strip).
- Secondary action: `[Abbrechen]`.
- After confirm: loader replaces the body (`"Branch wird erstellt..."`), dialog stays mounted. On 201: dismiss + switch to new branch. On error: show toast, dismiss dialog, stay in parent.

### 6.4 Sync clone UX

Per Chris's choice: sync with loader, direct switch on completion.

- During the request (~500ms-3s for long sessions): dialog shows loader, parent UI is **not** blocked at the chat level — user can still scroll the parent's messages, but the sidebar / cockpit input area should be disabled to prevent confusion.
- On success: dialog closes, sidebar selection updates to the new branch, `ChatView` swaps and runs its normal `getMessages` load (which uses the d-13 reconciliation buffer just shipped).
- On failure: toast `"Branch konnte nicht erstellt werden"`, dialog stays in pre-loading state so user can retry or cancel.

### 6.5 Tool-call pill "not replayed — clone" subtitle

`frontend/src/features/chat/messagePill/*` (wherever tool-call pills render): when `event.cloned_from_branch === true`, show a small grey subtitle below the pill heading: `"Aus Parent geklont — nicht erneut ausgeführt"`. Same for artefact / image / knowledge / web-search pills. Subtle: not an alert, just informative.

### 6.6 Sidebar — what changes

**Nothing user-visible.** Branches appear as normal sessions, sorted by `updated_at` like everything else. No icon, no parent-link breadcrumb, no expand/collapse. The `forked_from` pointer is in the document but the sidebar doesn't read it for v0.2.0.

(Future: a "show branches of this session" affordance could read `forked_from` server-side. Out of scope.)

---

## 7. Edge cases

### 7.1 Branching while a stream is in flight on the parent

The branch endpoint reads from MongoDB; an in-flight stream on the parent has not yet persisted its assistant doc, so the branch's tail won't include it. Result: branch ends one turn behind the live parent if user branches mid-stream. Acceptable — UX intuition is "branch from the message I clicked, not from the stream you can't see yet".

### 7.2 Branch from a session with active compaction

Pre-flight check (§5.2) returns 409. Frontend shows: "Bitte warte, bis die Zusammenfassung fertig ist". Retry advice: 60s.

### 7.3 Branch from a compacted-out tail

Per Q3 (PRE-BRANCHING): full history is preserved in the DB even past compaction. The fork point can point at any message regardless of how many checkpoints have rolled over it. The cloned branch carries the relevant checkpoints (those whose `tail_start_message_id` is in the cloned message set) plus the messages, so the branch's first inference sees the same `<conversation_compact>` block the parent saw at that point.

### 7.4 Branch of a branch of a branch

Unbounded depth, per Chris's UX answer. Each branch is a fully independent session and can be re-branched. The `forked_from` chain is not walked at runtime; each branch points only to its immediate parent at clone time.

### 7.5 Parent deletion after branch creation

Branches stay. `forked_from.session_id` becomes a dangling pointer — that's fine, it's informational only. No cascade delete, no orphan cleanup.

### 7.6 Concurrent branch creation from the same parent

Two tabs branching simultaneously. The endpoint is transactional per request. The two requests serialise on `parent_session_id` reads. Each gets its own new session document with a unique `_id`. The sibling-variant-index computation in the name dialog (§6.3) is best-effort: if two tabs both compute "Variante 2", one gets it, the other ends up with a name collision that's purely cosmetic (the system doesn't enforce unique titles).

### 7.7 Branch from the session-start (no fork message)

The user wants to "duplicate this conversation from the very beginning, edit my first user message". UI: when the user edits the first user message + save+resend, the dialog is case 2 ("force branch") and `fork_message_id` is `None` (`null` on the wire). Backend special-cases this: clone the session document only (no messages), then frontend's `chat.send` writes the first user message in the new branch.

This is an uncommon case but it's the symmetric completion of the model. Implementing it: detect `fork_message_id is None` in `clone_session_at` and skip the message-cloning step.

---

## 8. Tests

### 8.1 Backend — `tests/test_branching.py` (new)

- **clone_basic**: parent with 4 messages, fork at message 2 (assistant). Branch has messages 1 and 2 with new _ids but same correlation_ids. session_seq re-stamped 1..2.
- **clone_preserves_extras**: parent's `extras.replay_tool_history = False`. Branch inherits.
- **clone_compaction_checkpoints**: parent has 2 checkpoints. Fork after checkpoint 1's tail_start. Branch carries only checkpoint 1 with re-mapped tail_start_message_id pointing into the cloned message ids.
- **clone_tool_events_flagged**: parent assistant has events with tool_call entries. Clone has same events but each carries `cloned_from_branch: true`.
- **clone_session_start_sentinel**: `fork_message_id is None` → new session with zero messages, forked_from points at session_start.
- **clone_rejects_user_fork_point**: passing a user message id as `fork_message_id` → 400.
- **clone_rejects_wrong_owner**: parent belongs to user A, user B requests clone → 404.
- **clone_under_compaction_lock**: 409.
- **clone_concurrency**: two `asyncio.gather` clone requests on the same parent → both succeed with distinct branch _ids.

### 8.2 Backend — integration with pair-by-correlation and reasoning replay

After branch creation, the new branch's first inference must:
- Use the cloned history (verify via mock orchestrator).
- Pair correctly via `correlation_id` (already shared with parent's docs).
- Replay reasoning if the cloned assistant doc had `tool_replay_at_save = True` (the cloned flag is preserved as-is).

Add one test in `tests/modules/chat/test_history_expansion.py` or new `test_branching_history.py`: build a cloned session fixture, run `_expand_history_doc` over the cloned docs, verify thinking_blocks + tool triplets all expand correctly.

### 8.3 Frontend — `frontend/src/features/chat/branching/__tests__/*` (new)

- **BranchNameDialog**: renders pre-filled default, accepts edit, cancel doesn't create, confirm calls clone API.
- **MessageList action buttons**: last-assistant shows [Regenerate]+[Branch]; non-last shows [Branch & Regenerate]+[Branch].
- **Edit + save-and-resend dialog (case 1)**: on last user msg, dialog appears with two options; on earlier user msg, name dialog appears directly.
- **Branch flow E2E (with mocked API)**: trigger branch → name dialog → confirm → POST hits clone endpoint → on 201 → sidebar gains new entry → ChatView switches.

### 8.4 Visual regression / smoke

Manual checklist (Chris runs):
- Create branch from middle of an existing chat. New session visible in sidebar, opens cleanly.
- Verify cloned tool-call pill shows "Aus Parent geklont — nicht erneut ausgeführt" subtitle.
- Verify parent untouched after branch.
- Delete branch → parent unaffected. Delete parent → branch still works (forked_from dangles silently).
- Branch a branch of a branch — sidebar populates correctly, no crashes.

---

## 9. Backwards compatibility

- New `forked_from` field on `ChatSessionDocument` defaults to `None`. Existing sessions deserialise unchanged.
- New `cloned_from_branch` flag on timeline events defaults to `False`. Existing events deserialise unchanged.
- No DB migration script.
- `fork_message_id` is `Optional[str]` on the request body; `None` is the documented "branch from session start" case. No magic strings.
- Endpoint is purely additive — existing chat APIs untouched.

---

## 10. What this does NOT include (deferred)

- **Branch merging back into parent** — explicitly not a feature (we're not git). No spec, no UI.
- **Visual tree view of branches** — sidebar treats branches as flat sessions per UX decision §6.6.
- **Per-session "show all branches forked from here"** — `forked_from` is queryable but no UI surfaces it in v0.2.0.
- **Bulk branch operations** ("delete all branches", "rename all variants of X") — out of scope.
- **Branch rename auto-bumping the variant counter** — initial name dialog handles uniqueness best-effort; collisions are cosmetic only.
- **Async clone with background job** — sync chosen by Chris; if a session is so large that the clone takes >5s we'll revisit.

---

## 11. Implementation order

Suggested subagent split: **one backend subagent**, **one frontend subagent**, run in **parallel** because the API boundary is the only shared surface (POST /branch endpoint + response shape).

### 11.1 Backend (one subagent)

1. `ForkedFromPointer` DTO in `shared/dtos/chat.py` (additive).
2. `ChatSessionDocument.forked_from` field in `_models.py`.
3. `cloned_from_branch: bool = False` field on all `TimelineEntry*` DTOs in `shared/dtos/chat.py`.
4. `ChatRepository.clone_session_at` method per §5.3, with full transaction handling.
5. New endpoint `POST /api/chat/sessions/{parent_session_id}/branch` in `_handlers.py`, wired through `ChatService`.
6. Emit `CHAT_SESSION_CREATED` event after success.
7. Tests per §8.1 + §8.2.
8. INSIGHTS.md entry (next free INS — INS-052 probably).

### 11.2 Frontend (one subagent, can run parallel)

1. `BranchNameDialog` component (§6.3).
2. Action-bar button updates on `MessageList` (§6.1) — conditional re-labelling of Regenerate, plus new Branch button.
3. Edit + save-and-resend dialog injection (§6.2).
4. Branch flow orchestration: dialog → API call → loader → switch session → optional follow-up `chat.send` / `chat.regenerate`.
5. Tool-call pill subtitle on `cloned_from_branch === true` events (§6.5).
6. `chatApi.branchSession(parentId, forkMessageId, name)` API client method.
7. Tests per §8.3.
8. INSIGHTS.md entry alongside the backend's (or sequential — pick the next number after backend lands).

### 11.3 Sequencing

- Both subagents work in parallel; the API contract (§5.1) is the synchronisation point and is fully specified above.
- Merge order: backend first (so the frontend can integration-test against the real endpoint), but the dispatch is parallel.

---

## 12. Risk assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Multi-doc transaction unsupported on some Mongo deployments | Low | Clone could be non-atomic | RS0 is mandatory per CLAUDE.md; documented assumption |
| Cloned attachment becomes dead link after parent delete | Certain | Read returns 404 on referenced asset | Accepted (Chris's Q1 answer); user feedback determines if we revisit |
| Tool-call cloned but its result is stale (e.g. last week's web search) | Certain | Model treats stale data as current | Accepted; deferred to 0.3.0 (PRE-BRANCHING Q9 tool-result truncation) |
| Variant name collision in name dialog | Low | Cosmetic only (two sessions with same title) | No enforcement; user can rename |
| Branch under compaction lock | Possible | 409 user has to retry | Frontend shows clear toast with reason |
| Sibling-index computation walks all sessions | Low (small sidebar) | Sub-millisecond | Best-effort; not server-validated |
| Concurrent branches from same parent race | Low | Both succeed independently | Transaction isolation per request |
| `forked_from` dangling after parent delete | Certain | None — pointer is informational | No cascade delete by design |

---

## 13. What this unblocks

- **v0.2.0 ships.** This is the flagship feature.
- A foundation for future "branch list view per parent session" if user feedback demands it (read `forked_from` server-side).
- A clean substrate for future features like "compare two branches side-by-side" — the docs are independent so no coupling concerns.
- All prior work (session_seq, reasoning replay, pair-by-correlation, per-turn flag, race fixes) composes cleanly: each branch is just a normal session with normal documents.
