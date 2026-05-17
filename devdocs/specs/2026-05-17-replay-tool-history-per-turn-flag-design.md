# Per-Turn Persistence for `replay_tool_history` — Design Specification

**Date:** 2026-05-17
**Status:** Approved (pre-implementation)
**Source brief:** Follow-up to [reasoning + tool replay spec §6.2](2026-05-17-reasoning-tool-replay-design.md). Decided in-session 2026-05-17 with Chris.
**Scope:** Make the `replay_tool_history` flag historically stable per turn. The live session toggle controls only what is written to NEW turns; the history-expansion logic reads the flag from each stored assistant document, not from the current session extras.

---

## 1. Problem statement

The just-shipped reasoning + tool replay spec
(`devdocs/specs/2026-05-17-reasoning-tool-replay-design.md`) introduced
`ChatSessionExtras.replay_tool_history: bool` as a session-level toggle.
At history-expansion time, the orchestrator currently reads the live
value via `extras.replay_tool_history` and applies it to every past
turn in the session.

That makes the toggle **retroactive**. If a user toggles it off after a
multi-turn tool-using conversation, the context-fill ampel jumps down
instantly because every prior tool-using turn becomes shorter in the
re-built prompt. Toggle back on: jumps up. Predictable, but jarring,
and the user's "the model already knew about that tool call" mental
model is violated.

Chris's decision: **persist the flag value per turn**, so each turn is
expanded with the policy that was active when it was originally
written. The live toggle only governs **future** turns.

---

## 2. Out of scope

- The cockpit toggle UI itself — see the separate
  `2026-05-17-replay-tool-history-toggle-ui-design.md` spec. This one
  is purely backend.
- Frontend race fixes d-6/d-13 — separate spec.
- Migration of legacy documents — handled implicitly via Pydantic
  default (see §3.2).

---

## 3. Data model

### 3.1 New field on assistant message documents

`ChatMessageDocument` in `backend/modules/chat/_models.py` gains:

```python
# Snapshot of ``session.extras.replay_tool_history`` at the moment
# this assistant turn was persisted. Read at history-expansion time
# so toggle changes do NOT alter how prior turns are re-injected.
# Default ``True`` preserves the pre-2026-05-17 behaviour for any
# document written before this spec lands.
tool_replay_at_save: bool = True
```

User documents do **not** carry this field — only assistants persist
tool-call narration that this flag governs.

### 3.2 Backwards-compat read (CLAUDE.md hard rule)

Pydantic default `True` covers:

- Legacy assistant docs written before this spec — they had no
  awareness of the flag, so "as if replay was on" is the safe
  default and matches what the orchestrator was doing for them
  yesterday.
- Old documents in production: no migration script needed; the field
  materialises with `True` on read.

### 3.3 No index, no schema migration

The field is opaque to queries (always read alongside the rest of the
assistant document). No index. No `0003_*.py` migration file required.

---

## 4. Code changes

### 4.1 Repository — `save_message`

`backend/modules/chat/_repository.py` — `save_message(...)`. Add an
optional kwarg passed through to the document dict:

```python
async def save_message(
    self,
    session_id: str,
    role: str,
    content: str,
    token_count: int,
    thinking: str | None = None,
    thinking_blocks: list[dict] | None = None,
    usage: dict | None = None,
    # ... existing kwargs ...
    correlation_id: str | None = None,
    user_id: str | None = None,
    # NEW. Only meaningful for ``role == "assistant"``. The orchestrator
    # supplies the value of ``session.extras.replay_tool_history`` at
    # inference start so the doc records the policy that produced it.
    tool_replay_at_save: bool | None = None,
) -> dict:
    ...
    if role == "assistant" and tool_replay_at_save is not None:
        doc["tool_replay_at_save"] = tool_replay_at_save
```

User-role writes never pass the kwarg → no extra field on user docs.
Assistant-role writes get the snapshot. Legacy callers that omit the
kwarg get `None`, which is conditionalised away — the document looks
exactly as it does today.

### 4.2 Orchestrator — capture at inference start

`backend/modules/chat/_orchestrator.py` — `save_fn` closure
(currently ~line 1241–1287). The closure already captures `extras`,
which is resolved once at the top of `run_inference`. Snapshot at that
point and thread through:

```python
# At the top of run_inference, after extras is resolved (~line 750-800):
replay_tool_history_snapshot = bool(extras.replay_tool_history)

# In save_fn:
doc = await repo.save_message(
    session_id,
    role="assistant",
    # ... existing args ...
    correlation_id=correlation_id,
    user_id=user_id,
    tool_replay_at_save=replay_tool_history_snapshot,
)
```

Crucial: the snapshot is taken at **inference start**, not at
`save_fn` call time. If the user toggles mid-stream, the in-flight
inference still records the value that was active when the turn
began. (Toggling mid-stream is rare; the consistency is what
matters.)

### 4.3 History expansion — read per-doc

`backend/modules/chat/_orchestrator.py` — `_expand_history_doc`.

Today's signature:

```python
def _expand_history_doc(
    doc: dict,
    *,
    replay_reasoning: bool,
    replay_tool_history: bool,
) -> list[CompletionMessage]:
```

Becomes:

```python
def _expand_history_doc(
    doc: dict,
    *,
    replay_reasoning: bool,
) -> list[CompletionMessage]:
    # ...
    if role != "assistant":
        return [CompletionMessage(role=role, content=content_parts)]

    # NEW: read the historical flag from the doc itself. Legacy docs
    # without the field default to True (Pydantic default), matching
    # their original behaviour.
    replay_tool_history = doc.get("tool_replay_at_save", True)

    thinking_blocks = (
        _build_thinking_blocks_for_replay(doc) if replay_reasoning else []
    )
    tool_calls: list[ToolCallResult] = []
    tool_messages: list[CompletionMessage] = []
    if replay_tool_history:
        tool_calls, tool_messages = _collect_tool_triplets(doc)
    # ... rest unchanged
```

### 4.4 Call site — remove `replay_tool_history` parameter

The history-build loop in `run_inference` (`backend/modules/chat/_orchestrator.py:~1048`):

```python
# Before:
for doc in selected_history:
    messages.extend(
        _expand_history_doc(
            doc,
            replay_reasoning=reasoning_cap.replay_reasoning,
            replay_tool_history=extras.replay_tool_history,  # REMOVE
        )
    )

# After:
for doc in selected_history:
    messages.extend(
        _expand_history_doc(
            doc,
            replay_reasoning=reasoning_cap.replay_reasoning,
        )
    )
```

### 4.5 `ChatSessionExtras.replay_tool_history` stays put

The field on `ChatSessionExtras` is unchanged. It still represents
"what shall I do NEXT turn" — i.e., the value that the orchestrator
snapshots into `tool_replay_at_save` when the next assistant
write happens. From the cockpit's perspective, nothing changes.

---

## 5. Backwards compatibility

- Existing assistant docs lack `tool_replay_at_save` → Pydantic
  default `True` → expansion behaves exactly as before. No surprise
  drop in token counts for users who haven't yet seen a toggle.
- Existing tests that build fixture assistant docs don't carry the
  field → they default to `True` → all existing pair-builder and
  expansion tests pass unchanged.
- `extras.replay_tool_history` semantics: still a session-level user
  preference. Its *effect* moved from "applied at expansion" to
  "snapshot at save". For a user who never toggles it, behaviour is
  identical.

---

## 6. Tests

### 6.1 Unit tests — `tests/modules/chat/test_history_expansion.py` (extend)

The existing test file from the reasoning + tool replay spec already
covers `_expand_history_doc` for the four `(replay_reasoning,
replay_tool_history)` combinations. After this change:

- Replace the `replay_tool_history` kwarg in test calls with
  per-doc `tool_replay_at_save` keys.
- Add new tests:
  - **Per-doc flag respected**: two assistant docs in history, one
    with `tool_replay_at_save=True` and one with `False`.
    Assert tool triplets are expanded only for the True doc.
  - **Default to True for legacy docs**: doc with no
    `tool_replay_at_save` key behaves as if `True`.

### 6.2 Repository test — `tests/test_chat_repo_phase2.py` (extend)

Smoke test similar to the correlation_id one:

```python
async def test_save_message_persists_replay_tool_history_flag(mock_db):
    # Pass tool_replay_at_save=False, assert the document
    # carries the field with that value.
    # Pass nothing, assert the field is absent (defaults to True on read).
```

### 6.3 Orchestrator integration

The smoke check that the snapshot threads correctly from `extras`
through `save_fn` to the document is end-to-end. The existing
inference-runner tests don't cover `extras` plumbing directly. Add
one focused unit test in
`tests/modules/chat/test_orchestrator_replay_snapshot.py` (or extend
an existing file if convenient):

- Mock `extras.replay_tool_history = False`.
- Run a turn through the runner with the orchestrator's `save_fn`.
- Assert `repo.save_message` was called with
  `tool_replay_at_save=False`.

---

## 7. Implementation order

1. Add `tool_replay_at_save: bool = True` to the assistant
   document model in `_models.py`. Backwards-compat read.
2. Repository — `save_message` accepts and persists the new kwarg.
   Repository tests.
3. Orchestrator — snapshot at inference start, thread through
   `save_fn`.
4. Orchestrator — `_expand_history_doc` reads the per-doc flag;
   call site stops passing `replay_tool_history`.
5. Test updates per §6.
6. INSIGHTS.md entry INS-049 (or sequential — check what's free).
7. `uv run pytest` clean.

---

## 8. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Legacy doc reads with absent flag | Certain | None — defaults to True | Pydantic default handles it |
| Inference start vs save_fn call mid-toggle | Rare | Inconsistency for that single turn | Snapshot at inference start, document the choice in the closure comment |
| Test fixtures missing the new field | Low | Tests still pass via default | Document the default in the new history expansion tests |
| Future "purge replayed tool history" feature | Out of scope | This spec doesn't block it; a future migration could rewrite the flag retroactively if desired | Defer; out of 0.2.0 |

---

## 9. What this unblocks

- The cockpit toggle UI (`replay-tool-history-toggle-ui-design.md`)
  can ship a stable user experience: toggle ergebnisse zappeln nicht,
  klare Erwartung "ab nächster Antwort".
- Branching: a branch clone copies the per-turn flag along with each
  message, so the branch's history is expanded identically to the
  parent's at fork time. The branch's *new* turns can then diverge by
  toggling. Clone-on-branch is unaffected by this change because the
  field is part of the document.
