# Compact and Continue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Subagents must NOT merge, push, or switch branches — those are reserved for the supervising session.

**Goal:** Let the user collapse the older portion of a long chat into a compact briefing while keeping the recent turns verbatim, so the model stays sharp and token-efficient. MVP scope: manual trigger plus a suggest-toast on 60% threshold cross; re-compact appends new checkpoints; Anthropic prompt-cache anchor is placed at the latest tail-start.

**Architecture:** Trigger is a WS request → Redis lock + pre-flight check → `JobType.CHAT_COMPACTION` job → LLM call against the persona's model → checkpoint appended to `ChatSessionDocument.compaction_checkpoints`. Inference reads the latest checkpoint, slices messages from `tail_start_message_id`, and injects the briefing as `<conversation_compact>` between memory layer and integration extensions inside the system prompt. Anthropic cache markers gain a `compact_anchor_index` parameter that replaces the heuristic block-boundary marker.

**Tech Stack:** Python (FastAPI, Pydantic v2), TypeScript (React, Vitest), pnpm, uv, MongoDB 7 RS0, Redis Streams.

**Spec:** `devdocs/specs/2026-05-15-compact-and-continue-design.md`

**Branch:** Working directly on `master`. Each task lands its own commit. At the very end the supervising session squashes the whole implementation (and the spec) into a single commit per the user's "one spec = one commit" preference.

---

## Phase Map

```
Phase 1: Shared contracts                       (foundation, no deps)
  Task 1.1: Topics constants
  Task 1.2: CompactionCheckpointDto
  Task 1.3: ChatCompaction*Event classes
  Task 1.4: JobType.CHAT_COMPACTION

Phase 2: Backend data model                     (deps on Phase 1.2)
  Task 2.1: CompactionCheckpoint document
  Task 2.2: ChatSessionDocument.compaction_checkpoints
  Task 2.3: Repository helpers (append + get_message)
  Task 2.4: Backwards-compat test

Phase 3: Job handler                            (deps on Phases 1, 2)
  Task 3.1: Tail-determination helper + test
  Task 3.2: Source-range + sanitisation helper + test
  Task 3.3: Output validation helper + test
  Task 3.4: Compaction-prompt builder + test
  Task 3.5: Job handler skeleton (no LLM call yet)
  Task 3.6: Wire LLM call + retry + truncation
  Task 3.7: Persist + emit completed event
  Task 3.8: Register in JOB_REGISTRY

Phase 4: Inference slicing + Anthropic cache    (deps on Phase 2)
  Task 4.1: assemble() compact_markdown parameter
  Task 4.2: run_inference slicing
  Task 4.3: CompletionRequest.compact_anchor_index
  Task 4.4: compute_cache_markers compact_anchor parameter + tests
  Task 4.5: Adapter wiring (openrouter + nano-gpt)
  Task 4.6: Pipe compact_anchor_index from run_inference

Phase 5: Edit protection                        (deps on Phase 2)
  Task 5.1: handle_chat_edit guard + test
  Task 5.2: handle_chat_regenerate guard (if applicable)

Phase 6: Trigger handler                        (deps on Phases 1, 2, 3)
  Task 6.1: handle_chat_compaction_request — basic validation
  Task 6.2: Redis lock acquire/release
  Task 6.3: Pre-flight check + source/tail computation
  Task 6.4: Submit job + emit started event
  Task 6.5: WS-router wiring

Phase 7: Frontend session store + WS            (deps on Phase 1)
  Task 7.1: TS DTOs (mirror shared)
  Task 7.2: chatStore: compaction_checkpoints + helpers
  Task 7.3: useChatStream: subscribe to the 4 topics

Phase 8: Sparkly button                         (deps on Phase 7)
  Task 8.1: useCompactionState hook (button state machine)
  Task 8.2: SparkleCompactButton component
  Task 8.3: CompactConfirmCard component
  Task 8.4: Desktop placement in ChatView top-bar
  Task 8.5: Mobile placement in indicator row
  Task 8.6: Loading overlay for input area

Phase 9: Suggest toast                          (deps on Phase 7)
  Task 9.1: Threshold-cross detector hook
  Task 9.2: SuggestCompactToast component (+ voice suppression)

Phase 10: Compacted marker + drawer             (deps on Phase 7)
  Task 10.1: TimelineEntry 'compacted' kind type
  Task 10.2: CompactedMarkerPill component
  Task 10.3: MessageList renderer wiring
  Task 10.4: CompactedSnapshotDrawer (desktop slide-over)
  Task 10.5: Mobile bottom-sheet variant

Phase 11: Result toasts                         (deps on Phase 7)
  Task 11.1: Success toast on COMPLETED
  Task 11.2: Failure toast with retry on FAILED
  Task 11.3: 90s soft-timeout on loading overlay

Phase 12: Verification                          (deps on all)
  Task 12.1: Backend + frontend build sweep
  Task 12.2: Manual verification checklist (Chris)
```

---

## Test Execution Notes for Subagents

- **Backend tests on host:** Most pytest suites run fine on the host; tests that require MongoDB do NOT (Docker only). Tasks below mark host-OK vs docker-only.
- **Backend syntax check:** `uv run python -m py_compile <file>` after every Python edit.
- **Frontend build:** `pnpm run build` (NOT `pnpm tsc --noEmit` — the former catches stricter project-reference errors).
- **Frontend tests:** `pnpm vitest run <path>` targeted, `pnpm vitest run` full.
- **Subagents must not merge, push, force-push, or run `git reset --hard`.** Each task ends with a normal commit on the current branch.

---

## Phase 1: Shared Contracts

### Task 1.1: Topics constants

**Files:**
- Modify: `shared/topics.py`

- [ ] **Step 1: Locate the Chat-inference topic group**

Open `shared/topics.py`. Find the block beginning at line ~71:

```
    CHAT_STREAM_STARTED = "chat.stream.started"
```

and the existing `CHAT_*` constants that follow.

- [ ] **Step 2: Add the four compaction topics**

Add directly after the existing `CHAT_TOOL_CALL_*` group (search for `CHAT_TOOL_CALL_DELTA` and add after the block it belongs to):

```python
    # Chat compaction
    CHAT_COMPACTION_REQUEST = "chat.compaction.request"
    CHAT_COMPACTION_STARTED = "chat.compaction.started"
    CHAT_COMPACTION_PROGRESS = "chat.compaction.progress"
    CHAT_COMPACTION_COMPLETED = "chat.compaction.completed"
    CHAT_COMPACTION_FAILED = "chat.compaction.failed"
```

- [ ] **Step 3: Verify syntax**

Run: `uv run python -m py_compile shared/topics.py`
Expected: exit code 0, no output.

- [ ] **Step 4: Commit**

```bash
git add shared/topics.py
git commit -m "Add chat compaction topics"
```

---

### Task 1.2: CompactionCheckpointDto

**Files:**
- Modify: `shared/dtos/chat.py`

- [ ] **Step 1: Open file and locate import block**

Open `shared/dtos/chat.py`. Locate the existing `datetime` and `pydantic` imports at the top.

- [ ] **Step 2: Add the DTO**

Append at the end of the file:

```python
class CompactionCheckpointDto(BaseModel):
    """Snapshot of a chat compaction. Stored inside ChatSessionDocument
    and exposed unchanged in events. Append-only: each compact creates a
    new checkpoint; the model only ever sees the latest one as
    `<conversation_compact>`, but the UI renders all of them as markers.
    """

    id: str
    created_at: datetime
    model_unique_id: str
    summary_markdown: str
    last_message_id_before: str
    tail_start_message_id: str
    tokens_before: int
    tokens_after: int
    tail_token_count: int
    prev_checkpoint_id: str | None = None
```

- [ ] **Step 3: Verify syntax**

Run: `uv run python -m py_compile shared/dtos/chat.py`
Expected: exit code 0.

- [ ] **Step 4: Commit**

```bash
git add shared/dtos/chat.py
git commit -m "Add CompactionCheckpointDto"
```

---

### Task 1.3: ChatCompaction*Event classes

**Files:**
- Modify: `shared/events/chat.py`

- [ ] **Step 1: Open the file and confirm imports**

Open `shared/events/chat.py`. The top of the file already has:

```python
from datetime import datetime
from typing import Literal
from pydantic import BaseModel
from shared.dtos.chat import ArtefactRefDto, ChatSessionExtras
```

Modify the `shared.dtos.chat` import to also include the new DTO:

```python
from shared.dtos.chat import ArtefactRefDto, ChatSessionExtras, CompactionCheckpointDto
```

- [ ] **Step 2: Add the four event classes**

Append at the end of the file:

```python
class ChatCompactionStartedEvent(BaseModel):
    type: str = "chat.compaction.started"
    session_id: str
    correlation_id: str
    tokens_before: int
    estimated_tokens_after: int
    tail_message_count: int
    timestamp: datetime


class ChatCompactionProgressEvent(BaseModel):
    type: str = "chat.compaction.progress"
    session_id: str
    correlation_id: str
    stage: Literal["preparing", "calling_model", "validating", "persisting"]
    timestamp: datetime


class ChatCompactionCompletedEvent(BaseModel):
    type: str = "chat.compaction.completed"
    session_id: str
    correlation_id: str
    checkpoint: CompactionCheckpointDto
    tokens_saved: int
    new_context_used_tokens: int
    new_context_fill_percentage: float
    truncated_message_count: int = 0
    timestamp: datetime


class ChatCompactionFailedEvent(BaseModel):
    type: str = "chat.compaction.failed"
    session_id: str
    correlation_id: str
    error_code: Literal[
        "compaction_source_too_large",
        "below_threshold",
        "too_small",
        "already_running",
        "llm_failed",
        "validation_failed",
        "unknown",
    ]
    user_message: str
    recoverable: bool
    timestamp: datetime
```

- [ ] **Step 3: Verify syntax**

Run: `uv run python -m py_compile shared/events/chat.py`
Expected: exit code 0.

- [ ] **Step 4: Commit**

```bash
git add shared/events/chat.py
git commit -m "Add chat compaction events"
```

---

### Task 1.4: JobType.CHAT_COMPACTION

**Files:**
- Modify: `backend/jobs/_models.py`

- [ ] **Step 1: Locate the JobType enum**

Open `backend/jobs/_models.py`. The enum is at line 10 with members `TITLE_GENERATION`, `MEMORY_EXTRACTION`, `MEMORY_CONSOLIDATION`, etc.

- [ ] **Step 2: Add the new member**

Add directly after `MEMORY_CONSOLIDATION`:

```python
    CHAT_COMPACTION = "chat_compaction"
```

- [ ] **Step 3: Verify syntax**

Run: `uv run python -m py_compile backend/jobs/_models.py`
Expected: exit code 0.

- [ ] **Step 4: Commit**

```bash
git add backend/jobs/_models.py
git commit -m "Add CHAT_COMPACTION job type"
```

---

## Phase 2: Backend Data Model

### Task 2.1: CompactionCheckpoint document model

**Files:**
- Modify: `backend/modules/chat/_models.py`

- [ ] **Step 1: Confirm existing imports**

Open `backend/modules/chat/_models.py`. The top has:

```python
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field
from shared.dtos.chat import ChatSessionExtras
```

- [ ] **Step 2: Add the import for the shared DTO and the model**

Modify the `shared.dtos.chat` import:

```python
from shared.dtos.chat import ChatSessionExtras, CompactionCheckpointDto
```

Append after `ChatMessageDocument`:

```python
# The document and the DTO are structurally identical — we reuse the
# DTO directly inside the document model to keep both shapes guaranteed
# in lock-step. Each new checkpoint is appended; the inference path
# only ever uses the latest entry.
CompactionCheckpoint = CompactionCheckpointDto
```

- [ ] **Step 3: Verify syntax**

Run: `uv run python -m py_compile backend/modules/chat/_models.py`
Expected: exit code 0.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/chat/_models.py
git commit -m "Alias CompactionCheckpoint to shared DTO"
```

---

### Task 2.2: ChatSessionDocument.compaction_checkpoints field

**Files:**
- Modify: `backend/modules/chat/_models.py`

- [ ] **Step 1: Add the field to ChatSessionDocument**

In `backend/modules/chat/_models.py`, inside the `ChatSessionDocument` class, right before `created_at: datetime`, add:

```python
    # Chat compaction checkpoints — append-only. Default [] keeps pre-feature
    # sessions deserialising without error. See devdocs/specs/2026-05-15-compact-and-continue-design.md.
    compaction_checkpoints: list[CompactionCheckpoint] = Field(default_factory=list)
```

- [ ] **Step 2: Verify syntax**

Run: `uv run python -m py_compile backend/modules/chat/_models.py`
Expected: exit code 0.

- [ ] **Step 3: Commit**

```bash
git add backend/modules/chat/_models.py
git commit -m "Add compaction_checkpoints field to ChatSessionDocument"
```

---

### Task 2.3: Repository helpers

**Files:**
- Modify: `backend/modules/chat/_repository.py`

- [ ] **Step 1: Find a suitable location**

Open `backend/modules/chat/_repository.py`. Look for an existing method on `ChatRepository` such as `update_session_state` or `update_session_extras` — they are good reference points for the methods we add (they call `self._sessions.update_one(...)`).

- [ ] **Step 2: Add append_compaction_checkpoint**

Add as a new method on `ChatRepository`:

```python
    async def append_compaction_checkpoint(
        self, session_id: str, checkpoint: "CompactionCheckpoint",
    ) -> None:
        """Append a compaction checkpoint to a session document."""
        await self._sessions.update_one(
            {"_id": session_id},
            {
                "$push": {"compaction_checkpoints": checkpoint.model_dump(mode="json")},
                "$set": {"updated_at": datetime.now(timezone.utc)},
            },
        )
```

Also ensure these imports exist at the top of the file (add what's missing):

```python
from datetime import timezone
from backend.modules.chat._models import CompactionCheckpoint
```

- [ ] **Step 3: Add get_message helper if missing**

Search the file for `async def get_message`. If it does not exist, add:

```python
    async def get_message(self, message_id: str) -> dict | None:
        """Fetch a single message document by id."""
        return await self._messages.find_one({"_id": message_id})
```

If a similar helper already exists under a different name, note its name — later tasks reference `get_message`; rename in their call sites instead.

- [ ] **Step 4: Verify syntax**

Run: `uv run python -m py_compile backend/modules/chat/_repository.py`
Expected: exit code 0.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/chat/_repository.py
git commit -m "Add compaction repository helpers"
```

---

### Task 2.4: Backwards-compat test

**Files:**
- Create: `backend/tests/modules/chat/test_session_compaction_field.py`

- [ ] **Step 1: Write the test**

```python
"""Verify ChatSessionDocument deserialises pre-feature documents (no
compaction_checkpoints field) without error and defaults to an empty list."""

from datetime import datetime, timezone

from backend.modules.chat._models import ChatSessionDocument


def test_legacy_session_deserialises_with_empty_checkpoints():
    doc = {
        "_id": "session-abc",
        "user_id": "u1",
        "persona_id": "p1",
        "state": "idle",
        "pinned": False,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    session = ChatSessionDocument.model_validate(doc)
    assert session.compaction_checkpoints == []


def test_session_with_one_checkpoint_round_trips():
    cp = {
        "id": "cp-1",
        "created_at": datetime.now(timezone.utc),
        "model_unique_id": "ollama:llama3.2",
        "summary_markdown": "## Topic & Goal\nx\n",
        "last_message_id_before": "m-9",
        "tail_start_message_id": "m-10",
        "tokens_before": 100,
        "tokens_after": 20,
        "tail_token_count": 80,
        "prev_checkpoint_id": None,
    }
    doc = {
        "_id": "session-abc",
        "user_id": "u1",
        "persona_id": "p1",
        "state": "idle",
        "pinned": False,
        "compaction_checkpoints": [cp],
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    session = ChatSessionDocument.model_validate(doc)
    assert len(session.compaction_checkpoints) == 1
    assert session.compaction_checkpoints[0].id == "cp-1"
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest backend/tests/modules/chat/test_session_compaction_field.py -v`
Expected: 2 passed.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/modules/chat/test_session_compaction_field.py
git commit -m "Test ChatSessionDocument backwards-compat for compaction field"
```

---

## Phase 3: Job Handler

### Task 3.1: Tail-determination helper

**Files:**
- Create: `backend/modules/chat/_compaction.py`
- Create: `backend/tests/modules/chat/test_compaction_tail.py`

- [ ] **Step 1: Write the failing test first**

`backend/tests/modules/chat/test_compaction_tail.py`:

```python
"""Tail determination: 6 turns OR 20% of model context, whichever is larger."""

from backend.modules.chat._compaction import determine_tail_start_index


def _msgs(n: int, tokens_per: int = 100) -> list[dict]:
    return [
        {"_id": f"m-{i}", "role": "user" if i % 2 == 0 else "assistant",
         "token_count": tokens_per}
        for i in range(n)
    ]


def test_short_session_returns_index_zero():
    # 4 messages, far below 12-message floor: whole list is tail
    msgs = _msgs(4)
    assert determine_tail_start_index(msgs, model_context=10_000) == 0


def test_long_session_uses_12_message_floor():
    # 100 messages of 100 tokens; 20% of 200k context = 40k tokens
    # 12 messages * 100 = 1200 tokens — smaller than 20% rule (40k)
    # Larger of the two => 40k tokens => 400 messages... clipped to 100
    msgs = _msgs(100, tokens_per=100)
    idx = determine_tail_start_index(msgs, model_context=200_000)
    # 20% rule applies; since 20% > all tokens, tail starts at 0
    assert idx == 0


def test_long_session_uses_token_budget_when_larger():
    # 100 messages of 1000 tokens each = 100k total
    # 12-msg floor: 12 * 1000 = 12k tokens
    # 20% of 50k context = 10k tokens
    # 12-msg floor wins => 12 messages of tail => start at index 88
    msgs = _msgs(100, tokens_per=1000)
    idx = determine_tail_start_index(msgs, model_context=50_000)
    assert idx == 88


def test_long_session_uses_floor_token_rule_when_larger():
    # 100 messages of 100 tokens = 10k total
    # 12-msg floor: 1.2k tokens
    # 20% of 100k context = 20k tokens — but only 10k available
    # 20% rule => take everything => index 0
    msgs = _msgs(100, tokens_per=100)
    idx = determine_tail_start_index(msgs, model_context=100_000)
    assert idx == 0
```

- [ ] **Step 2: Run the test — expect ImportError/fail**

Run: `uv run pytest backend/tests/modules/chat/test_compaction_tail.py -v`
Expected: collection error or failures (helper not implemented yet).

- [ ] **Step 3: Implement the helper**

`backend/modules/chat/_compaction.py`:

```python
"""Pure helpers for chat compaction (no IO, no LLM calls).

The job handler in backend/jobs/handlers/_chat_compaction.py composes
these functions with the repository, the LLM client, and the event bus.
"""

from __future__ import annotations

from typing import Iterable


_MIN_TAIL_MESSAGES = 12      # 6 turns
_TAIL_TOKEN_FRACTION = 0.20  # 20 % of model context


def determine_tail_start_index(
    messages: list[dict], *, model_context: int,
) -> int:
    """Return the index of the first message that must stay in the tail.

    Walks newest → oldest, accumulating ``token_count``. The tail extends
    until BOTH the 6-turn floor (12 messages) AND the 20% token rule are
    satisfied — i.e. whichever rule yields the LARGER tail wins.
    """
    if not messages:
        return 0

    total = len(messages)
    token_budget = int(model_context * _TAIL_TOKEN_FRACTION)

    tail_tokens = 0
    chosen_idx = total  # exclusive — adjust as we walk
    for i in range(total - 1, -1, -1):
        tail_tokens += int(messages[i].get("token_count") or 0)
        tail_messages = total - i
        if tail_messages >= _MIN_TAIL_MESSAGES and tail_tokens >= token_budget:
            chosen_idx = i
            break
        chosen_idx = i

    return max(0, chosen_idx)
```

- [ ] **Step 4: Re-run the test**

Run: `uv run pytest backend/tests/modules/chat/test_compaction_tail.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/chat/_compaction.py backend/tests/modules/chat/test_compaction_tail.py
git commit -m "Add tail-determination helper for chat compaction"
```

---

### Task 3.2: Source range + sanitisation

**Files:**
- Modify: `backend/modules/chat/_compaction.py`
- Modify: `backend/tests/modules/chat/test_compaction_tail.py`

- [ ] **Step 1: Add the test (append to existing test file)**

```python
from backend.modules.chat._compaction import (
    determine_tail_start_index,
    sanitise_source,
    select_source_range,
)


def test_select_source_range_no_prev_checkpoint():
    msgs = _msgs(20, tokens_per=10)
    source, tail = select_source_range(msgs, tail_start_index=15, prev_tail_start_id=None)
    assert len(source) == 15
    assert source[-1]["_id"] == "m-14"
    assert len(tail) == 5


def test_select_source_range_with_prev_checkpoint():
    msgs = _msgs(20, tokens_per=10)
    # Prev tail-start was at m-5; new tail-start at m-15
    source, tail = select_source_range(
        msgs, tail_start_index=15, prev_tail_start_id="m-5",
    )
    assert [m["_id"] for m in source] == [f"m-{i}" for i in range(5, 15)]


def test_sanitise_source_drops_tool_roles_and_tool_call_assistants():
    msgs = [
        {"_id": "m-1", "role": "user", "content": "hi", "token_count": 2},
        {"_id": "m-2", "role": "assistant", "content": "hello", "token_count": 2},
        {"_id": "m-3", "role": "tool", "content": "{}", "token_count": 1},
        {"_id": "m-4", "role": "assistant", "content": "", "token_count": 0},
        {"_id": "m-5", "role": "assistant", "content": "back to text", "token_count": 3},
    ]
    cleaned = sanitise_source(msgs)
    assert [m["_id"] for m in cleaned] == ["m-1", "m-2", "m-5"]
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest backend/tests/modules/chat/test_compaction_tail.py -v`
Expected: 3 new tests fail with ImportError.

- [ ] **Step 3: Implement the helpers**

Append to `backend/modules/chat/_compaction.py`:

```python
def select_source_range(
    messages: list[dict],
    *,
    tail_start_index: int,
    prev_tail_start_id: str | None,
) -> tuple[list[dict], list[dict]]:
    """Split messages into source range (to be compacted) and tail.

    When ``prev_tail_start_id`` is provided, the source begins at that
    message (re-compact case: only the messages added since the previous
    checkpoint are condensed; the previous compact-markdown is folded in
    as Previous Story by the prompt builder).
    """
    tail = messages[tail_start_index:]
    if prev_tail_start_id is None:
        source = messages[:tail_start_index]
    else:
        start = next(
            (i for i, m in enumerate(messages) if m["_id"] == prev_tail_start_id),
            0,
        )
        source = messages[start:tail_start_index]
    return source, tail


def sanitise_source(source: list[dict]) -> list[dict]:
    """Drop tool-role messages and assistant messages with empty content
    (which are typically pure tool-call wrappers). Keeps user and
    text-bearing assistant messages."""
    cleaned: list[dict] = []
    for m in source:
        role = m.get("role")
        if role == "tool":
            continue
        if role == "assistant" and not (m.get("content") or "").strip():
            continue
        cleaned.append(m)
    return cleaned
```

- [ ] **Step 4: Re-run the tests**

Run: `uv run pytest backend/tests/modules/chat/test_compaction_tail.py -v`
Expected: all 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/chat/_compaction.py backend/tests/modules/chat/test_compaction_tail.py
git commit -m "Add source-range + sanitisation helpers for compaction"
```

---

### Task 3.3: Output validation

**Files:**
- Modify: `backend/modules/chat/_compaction.py`
- Create: `backend/tests/modules/chat/test_compaction_validation.py`

- [ ] **Step 1: Write the test**

```python
"""Validate compact-markdown output against the required-sections contract."""

import pytest

from backend.modules.chat._compaction import (
    CompactionValidationError,
    validate_compact_markdown,
)


_GOOD_OUTPUT = """\
## Topic & Goal
This conversation is about X.

## Established Facts
- A
- B

## Open Threads
- C

## User Preferences Observed
- D

## Pending References
_(none)_

## Tone & Persona Adherence
Friendly.
"""


def test_valid_output_passes():
    validate_compact_markdown(_GOOD_OUTPUT)


def test_missing_section_raises():
    bad = _GOOD_OUTPUT.replace("## Open Threads", "## Random Heading")
    with pytest.raises(CompactionValidationError):
        validate_compact_markdown(bad)


def test_empty_raises():
    with pytest.raises(CompactionValidationError):
        validate_compact_markdown("")


def test_unclosed_code_fence_raises():
    bad = _GOOD_OUTPUT + "\n```\nleftover"
    with pytest.raises(CompactionValidationError):
        validate_compact_markdown(bad)
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest backend/tests/modules/chat/test_compaction_validation.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

Append to `backend/modules/chat/_compaction.py`:

```python
_REQUIRED_SECTIONS = (
    "## Topic & Goal",
    "## Established Facts",
    "## Open Threads",
    "## User Preferences Observed",
    "## Pending References",
    "## Tone & Persona Adherence",
)


class CompactionValidationError(Exception):
    """Raised when a compact-markdown output fails structural checks."""


def validate_compact_markdown(markdown: str) -> None:
    """Raise CompactionValidationError if markdown is not a valid briefing.

    Checks: non-empty, all six required headings present, code fences
    balanced. The model's prose may otherwise vary freely.
    """
    text = (markdown or "").strip()
    if not text:
        raise CompactionValidationError("compact markdown was empty")

    missing = [s for s in _REQUIRED_SECTIONS if s not in text]
    if missing:
        raise CompactionValidationError(
            f"compact markdown missing required sections: {missing}",
        )

    fence_count = sum(1 for line in text.splitlines() if line.strip().startswith("```"))
    if fence_count % 2 != 0:
        raise CompactionValidationError("compact markdown has unbalanced code fence")
```

- [ ] **Step 4: Re-run**

Run: `uv run pytest backend/tests/modules/chat/test_compaction_validation.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/chat/_compaction.py backend/tests/modules/chat/test_compaction_validation.py
git commit -m "Add compaction output validation"
```

---

### Task 3.4: Compaction-prompt builder

**Files:**
- Modify: `backend/modules/chat/_compaction.py`
- Create: `backend/tests/modules/chat/test_compaction_prompt.py`

- [ ] **Step 1: Write the test**

```python
"""Compaction prompt builder — verifies that the system prompt and
transcript rendering are stable and that the previous-story block is
injected when re-compacting."""

from backend.modules.chat._compaction import (
    COMPACTION_RETRY_REMINDER,
    build_compaction_system_prompt,
    build_compaction_transcript,
)


def test_system_prompt_contains_required_section_headings():
    sp = build_compaction_system_prompt()
    for heading in (
        "## Topic & Goal",
        "## Established Facts",
        "## Open Threads",
        "## User Preferences Observed",
        "## Pending References",
        "## Tone & Persona Adherence",
    ):
        assert heading in sp


def test_retry_reminder_distinct_string():
    assert "MUST contain all six headings" in COMPACTION_RETRY_REMINDER


def test_transcript_simple_case():
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    txt = build_compaction_transcript(msgs, previous_summary=None)
    assert txt.startswith("User: hi")
    assert "Assistant: hello" in txt


def test_transcript_prepends_previous_summary_on_recompact():
    msgs = [{"role": "user", "content": "newer turn"}]
    prev = "## Topic & Goal\nOld stuff\n"
    txt = build_compaction_transcript(msgs, previous_summary=prev)
    assert "Previous Story (from earlier checkpoint)" in txt
    assert "Old stuff" in txt
    assert txt.index("Old stuff") < txt.index("newer turn")
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest backend/tests/modules/chat/test_compaction_prompt.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

Append to `backend/modules/chat/_compaction.py`:

```python
COMPACTION_SYSTEM_PROMPT_TOKENS = 380   # rough estimate, used by pre-flight
COMPACTION_MAX_OUTPUT_TOKENS = 2000
COMPACTION_SAFETY_MARGIN = 1000


COMPACTION_RETRY_REMINDER = (
    "\n\nIMPORTANT: The previous attempt was missing required sections. "
    "Output MUST contain all six headings exactly as specified, in the "
    "order shown."
)


def build_compaction_system_prompt() -> str:
    """Verbatim system prompt for compaction jobs. See spec §6.4."""
    return (
        "You are a conversation-compaction assistant. Below is a transcript "
        "of a conversation between a user and an AI assistant. Your job is "
        "to extract a structured briefing that allows another AI to "
        "seamlessly continue this conversation in a new context window.\n\n"
        "Output rules:\n"
        "- Output Markdown only. No preamble, no \"I have summarised\", no "
        "meta-commentary.\n"
        "- Use the exact section headings shown below, in order.\n"
        "- Be terse but complete. Aim for 5–10 % of the original token count.\n"
        "- Preserve the user's language preferences, name, and any "
        "established facts about them.\n"
        "- Quote critical user phrasings verbatim if they carry intent "
        "(e.g. preferences, decisions).\n"
        "- Do not invent information. If a section has no content, write "
        "\"_(none)_\".\n\n"
        "Required sections:\n\n"
        "## Topic & Goal\n"
        "What is this conversation about? What is the user trying to achieve?\n\n"
        "## Established Facts\n"
        "Concrete facts, decisions, names, numbers, conclusions reached. Bullet list.\n\n"
        "## Open Threads\n"
        "Questions left unanswered, things the user said they would come back to.\n\n"
        "## User Preferences Observed\n"
        "Communication style, expertise level, language preferences, "
        "anything that should shape how the next AI responds.\n\n"
        "## Pending References\n"
        "Files, URLs, artefacts, tools that the user mentioned and that "
        "the next assistant should know about. Do not paste their content "
        "— just reference them by name.\n\n"
        "## Tone & Persona Adherence\n"
        "One sentence on how the persona has been speaking (formal/informal, etc.).\n"
    )


def build_compaction_transcript(
    source_messages: list[dict],
    *,
    previous_summary: str | None,
) -> str:
    """Render the user-prompt content for a compaction call.

    On re-compact, prepends the previous checkpoint's markdown as a
    'Previous Story' block so no information is lost across compactions.
    """
    parts: list[str] = []
    if previous_summary:
        parts.append("## Previous Story (from earlier checkpoint)\n\n"
                     f"{previous_summary.strip()}\n\n"
                     "---\n\n"
                     "## Conversation since the previous checkpoint\n")
    for m in source_messages:
        role = (m.get("role") or "user").capitalize()
        content = (m.get("content") or "").strip()
        if content:
            parts.append(f"{role}: {content}")
    return "\n".join(parts)
```

- [ ] **Step 4: Re-run**

Run: `uv run pytest backend/tests/modules/chat/test_compaction_prompt.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/chat/_compaction.py backend/tests/modules/chat/test_compaction_prompt.py
git commit -m "Add compaction prompt builder"
```

---

### Task 3.5: Job handler skeleton

**Files:**
- Create: `backend/jobs/handlers/_chat_compaction.py`

- [ ] **Step 1: Create the file with the skeleton**

```python
"""Job handler — chat compaction.

Condenses the source range of a chat session into a markdown briefing
and appends a CompactionCheckpoint to the session document. The
inference path reads only the latest checkpoint and slices the message
history from its tail_start_message_id.
"""

import structlog
from datetime import UTC, datetime
from uuid import uuid4

from backend.jobs._models import JobConfig, JobEntry
from backend.modules.chat._compaction import (
    COMPACTION_MAX_OUTPUT_TOKENS,
    COMPACTION_RETRY_REMINDER,
    CompactionValidationError,
    build_compaction_system_prompt,
    build_compaction_transcript,
    determine_tail_start_index,
    sanitise_source,
    select_source_range,
    validate_compact_markdown,
)
from shared.events.chat import (
    ChatCompactionCompletedEvent,
    ChatCompactionFailedEvent,
    ChatCompactionProgressEvent,
)
from shared.dtos.chat import CompactionCheckpointDto, ChatSessionExtras
from shared.dtos.inference import CompletionMessage, CompletionRequest, ContentPart
from shared.dtos.llm import ReasoningCapability, ToolCapability
from shared.topics import Topics

_log = structlog.get_logger(__name__)


async def handle_chat_compaction(
    job: JobEntry,
    config: JobConfig,
    redis,
    event_bus,
) -> None:
    """Run the compaction job. See devdocs/specs/2026-05-15-compact-and-continue-design.md §6.2."""
    from backend.database import get_db
    from backend.modules.chat._repository import ChatRepository
    from backend.modules.llm import get_effective_context_window

    token_key = f"job:executed:{job.execution_token}"
    already = await redis.set(token_key, "1", nx=True, ex=48 * 3600)
    if already is None:
        _log.info("job.duplicate_skip token=%s job_id=%s",
                  job.execution_token, job.id)
        return

    session_id = job.payload["session_id"]
    correlation_id = job.payload.get("correlation_id") or job.correlation_id
    prev_checkpoint_id = job.payload.get("prev_checkpoint_id")

    lock_key = f"compaction:lock:{session_id}"

    db = get_db()
    repo = ChatRepository(db)

    try:
        # Stub — wired in 3.6/3.7
        _log.info("compaction.skeleton_run", session_id=session_id)
    finally:
        await redis.delete(lock_key)
```

- [ ] **Step 2: Verify syntax**

Run: `uv run python -m py_compile backend/jobs/handlers/_chat_compaction.py`
Expected: exit code 0.

- [ ] **Step 3: Commit**

```bash
git add backend/jobs/handlers/_chat_compaction.py
git commit -m "Add chat compaction job handler skeleton"
```

---

### Task 3.6: Wire LLM call, retry, truncation

**Files:**
- Modify: `backend/jobs/handlers/_chat_compaction.py`

- [ ] **Step 1: Replace the try/finally body**

Replace the entire `try: ... finally: await redis.delete(lock_key)` block with the full job logic:

```python
    try:
        session = await repo.get_session_by_id(session_id, job.user_id)
        if session is None:
            _log.warning("compaction.session_missing", session_id=session_id)
            return

        all_messages = await repo.list_messages(session_id)
        model_context = (
            await get_effective_context_window(job.user_id, job.model_unique_id)
            or 8192
        )

        prev_tail_start_id = None
        previous_summary = None
        checkpoints = session.get("compaction_checkpoints") or []
        if prev_checkpoint_id:
            for cp in checkpoints:
                if cp["id"] == prev_checkpoint_id:
                    prev_tail_start_id = cp["tail_start_message_id"]
                    previous_summary = cp["summary_markdown"]
                    break

        tail_start_idx = determine_tail_start_index(
            all_messages, model_context=model_context,
        )
        source_msgs_raw, tail_msgs = select_source_range(
            all_messages,
            tail_start_index=tail_start_idx,
            prev_tail_start_id=prev_tail_start_id,
        )
        source_msgs = sanitise_source(source_msgs_raw)
        tail_start_message_id = (
            tail_msgs[0]["_id"] if tail_msgs else all_messages[-1]["_id"]
        )

        # Truncation: drop oldest source messages until <= 70% of model context.
        truncation_target = int(model_context * 0.70)
        truncated_count = 0
        while (
            sum(int(m.get("token_count") or 0) for m in source_msgs)
            > truncation_target
        ):
            source_msgs.pop(0)
            truncated_count += 1
        if truncated_count > 0:
            _log.warning(
                "compaction.source.truncated",
                count=truncated_count,
                session_id=session_id,
                correlation_id=correlation_id,
            )

        tokens_before = sum(int(m.get("token_count") or 0) for m in source_msgs)
        tail_token_count = sum(int(m.get("token_count") or 0) for m in tail_msgs)
        last_message_id_before = (
            source_msgs[-1]["_id"] if source_msgs else tail_start_message_id
        )

        await _emit_progress(event_bus, session_id, correlation_id, "calling_model", job.user_id)

        markdown = await _call_llm_with_retry(
            user_id=job.user_id,
            model_unique_id=job.model_unique_id,
            source_msgs=source_msgs,
            previous_summary=previous_summary,
            correlation_id=correlation_id,
        )

        await _emit_progress(event_bus, session_id, correlation_id, "persisting", job.user_id)

        from backend.token_counter import count_tokens
        from backend.modules.chat._models import CompactionCheckpoint

        tokens_after = count_tokens(markdown)
        checkpoint = CompactionCheckpoint(
            id=str(uuid4()),
            created_at=datetime.now(UTC),
            model_unique_id=job.model_unique_id,
            summary_markdown=markdown,
            last_message_id_before=last_message_id_before,
            tail_start_message_id=tail_start_message_id,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            tail_token_count=tail_token_count,
            prev_checkpoint_id=prev_checkpoint_id,
        )
        await repo.append_compaction_checkpoint(session_id, checkpoint)

        # Recompute session-context numbers after compact.
        new_used = tokens_after + tail_token_count
        new_fill = new_used / model_context if model_context else 0.0

        completed = ChatCompactionCompletedEvent(
            session_id=session_id,
            correlation_id=correlation_id,
            checkpoint=CompactionCheckpointDto(**checkpoint.model_dump()),
            tokens_saved=max(0, tokens_before - tokens_after),
            new_context_used_tokens=new_used,
            new_context_fill_percentage=new_fill,
            truncated_message_count=truncated_count,
            timestamp=datetime.now(UTC),
        )
        await event_bus.publish(
            Topics.CHAT_COMPACTION_COMPLETED,
            completed,
            scope=f"session:{session_id}",
            target_user_ids=[job.user_id],
            correlation_id=correlation_id,
        )
    except CompactionValidationError as exc:
        _log.exception("compaction.validation_failed", session_id=session_id)
        await _emit_failed(
            event_bus, session_id, correlation_id, job.user_id,
            error_code="validation_failed",
            user_message="The model could not produce a valid briefing. Please try again.",
            recoverable=True,
        )
    except Exception:
        _log.exception("compaction.llm_failed", session_id=session_id)
        await _emit_failed(
            event_bus, session_id, correlation_id, job.user_id,
            error_code="llm_failed",
            user_message="The model could not be reached. Please try again.",
            recoverable=True,
        )
    finally:
        await redis.delete(lock_key)
```

- [ ] **Step 2: Add the helpers below `handle_chat_compaction`**

```python
async def _emit_progress(event_bus, session_id, correlation_id, stage, user_id):
    await event_bus.publish(
        Topics.CHAT_COMPACTION_PROGRESS,
        ChatCompactionProgressEvent(
            session_id=session_id,
            correlation_id=correlation_id,
            stage=stage,
            timestamp=datetime.now(UTC),
        ),
        scope=f"session:{session_id}",
        target_user_ids=[user_id],
        correlation_id=correlation_id,
    )


async def _emit_failed(
    event_bus, session_id, correlation_id, user_id,
    *, error_code, user_message, recoverable,
):
    await event_bus.publish(
        Topics.CHAT_COMPACTION_FAILED,
        ChatCompactionFailedEvent(
            session_id=session_id,
            correlation_id=correlation_id,
            error_code=error_code,
            user_message=user_message,
            recoverable=recoverable,
            timestamp=datetime.now(UTC),
        ),
        scope=f"session:{session_id}",
        target_user_ids=[user_id],
        correlation_id=correlation_id,
    )


async def _call_llm_with_retry(
    *, user_id, model_unique_id, source_msgs, previous_summary, correlation_id,
):
    from backend.modules.llm import stream_completion

    system_prompt = build_compaction_system_prompt()
    transcript = build_compaction_transcript(
        source_msgs, previous_summary=previous_summary,
    )

    for attempt in (1, 2):
        sp = system_prompt + (
            COMPACTION_RETRY_REMINDER if attempt == 2 else ""
        )
        messages = [
            CompletionMessage(role="system", content=[ContentPart(type="text", text=sp)]),
            CompletionMessage(role="user", content=[ContentPart(type="text", text=transcript)]),
        ]
        request = CompletionRequest(
            model=model_unique_id.split(":", 1)[1],
            messages=messages,
            temperature=0.3,
            reasoning=ReasoningCapability(kind="no_reasoning"),
            tools_capability=ToolCapability(supported=False),
            extras=ChatSessionExtras(
                tools_enabled=False, reasoning_mode="off", reasoning_effort=None,
            ),
        )
        collected: list[str] = []
        async for chunk in stream_completion(
            user_id=user_id,
            model_unique_id=model_unique_id,
            request=request,
            source="job:chat_compaction",
            correlation_id=correlation_id,
        ):
            if hasattr(chunk, "delta") and chunk.delta:
                collected.append(chunk.delta)
        markdown = "".join(collected).strip()
        try:
            validate_compact_markdown(markdown)
            return markdown
        except CompactionValidationError:
            if attempt == 2:
                raise
            _log.warning(
                "compaction.validation_retry",
                correlation_id=correlation_id,
            )
    raise CompactionValidationError("exhausted retries")
```

**Note for the implementing subagent:** The exact `stream_completion` signature and chunk shape may differ from this sketch (the underlying API is `backend/modules/llm/__init__.py:140`). Adjust the loop to match — read the function signature and reference `_memory_consolidation.py` for the canonical pattern. The intent: collect text deltas into `markdown` and call `validate_compact_markdown`.

- [ ] **Step 3: Verify syntax**

Run: `uv run python -m py_compile backend/jobs/handlers/_chat_compaction.py`
Expected: exit code 0.

- [ ] **Step 4: Commit**

```bash
git add backend/jobs/handlers/_chat_compaction.py
git commit -m "Wire LLM call, retry, and truncation in chat-compaction handler"
```

---

### Task 3.7: Register in JOB_REGISTRY

**Files:**
- Modify: `backend/jobs/_registry.py`

- [ ] **Step 1: Add the import**

Open `backend/jobs/_registry.py`. After the existing `_memory_consolidation` import, add:

```python
from backend.jobs.handlers._chat_compaction import handle_chat_compaction
```

- [ ] **Step 2: Add the registry entry**

Inside `JOB_REGISTRY`, before the closing brace:

```python
    JobType.CHAT_COMPACTION: JobConfig(
        handler=handle_chat_compaction,
        max_retries=1,
        retry_delay_seconds=30.0,
        queue_timeout_seconds=3600.0,
        execution_timeout_seconds=120.0,
        reasoning_enabled=False,
        notify=True,
        notify_error=True,
    ),
```

- [ ] **Step 3: Verify syntax**

Run: `uv run python -m py_compile backend/jobs/_registry.py`
Expected: exit code 0.

- [ ] **Step 4: Commit**

```bash
git add backend/jobs/_registry.py
git commit -m "Register chat compaction in JOB_REGISTRY"
```

---

## Phase 4: Inference Slicing + Anthropic Cache

### Task 4.1: assemble() compact_markdown parameter

**Files:**
- Modify: `backend/modules/chat/_prompt_assembler.py`

- [ ] **Step 1: Extend the signature**

In `backend/modules/chat/_prompt_assembler.py`, change the `assemble()` signature (around line 77) to add a new keyword-only parameter:

```python
async def assemble(
    user_id: str,
    persona_id: str | None,
    model_unique_id: str,
    *,
    project_id: str | None = None,
    supports_reasoning: bool = False,
    extras: ChatSessionExtras | None = None,
    compact_markdown: str | None = None,
) -> str:
```

- [ ] **Step 2: Inject the block between memory and integration extensions**

In the same file, immediately after the memory-layer block (the section that ends with `parts.append(memory_xml)` around line 164) and before the integration-extensions import (around line 171), add:

```python
    # Compact-and-Continue: when the session carries an active compaction
    # checkpoint, the caller passes its markdown here so the model sees
    # the older portion of the conversation as a condensed briefing.
    if compact_markdown:
        parts.append(
            '<conversation_compact>\n'
            'The earlier portion of this conversation has been compacted '
            'into the briefing below. Use it as authoritative context. '
            'Do not refer to it explicitly unless the user asks about '
            'earlier topics.\n\n'
            f'{compact_markdown.strip()}\n'
            '</conversation_compact>'
        )
```

- [ ] **Step 3: Verify syntax**

Run: `uv run python -m py_compile backend/modules/chat/_prompt_assembler.py`
Expected: exit code 0.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/chat/_prompt_assembler.py
git commit -m "Add compact_markdown parameter to prompt assembler"
```

---

### Task 4.2: run_inference slicing

**Files:**
- Modify: `backend/modules/chat/_orchestrator.py`

- [ ] **Step 1: Locate the history-load block**

Open `backend/modules/chat/_orchestrator.py`. Around line 779 you'll find:

```python
    history_docs = await repo.list_messages(session_id)
    history_docs = _filter_usable_history(history_docs)
```

- [ ] **Step 2: Insert the slicing logic before `_filter_usable_history`**

Replace the two lines above with:

```python
    history_docs = await repo.list_messages(session_id)

    compact_markdown: str | None = None
    compact_anchor_index: int | None = None
    checkpoints = session.get("compaction_checkpoints") or []
    if checkpoints:
        latest = checkpoints[-1]
        tail_start_msg = next(
            (m for m in history_docs
             if m["_id"] == latest["tail_start_message_id"]),
            None,
        )
        if tail_start_msg is None:
            _log.error(
                "compaction.checkpoint.dangling session_id=%s tail_start=%s",
                session_id, latest["tail_start_message_id"],
            )
        else:
            cutoff = tail_start_msg["created_at"]
            history_docs = [m for m in history_docs if m["created_at"] >= cutoff]
            compact_markdown = latest["summary_markdown"]

    history_docs = _filter_usable_history(history_docs)
```

- [ ] **Step 3: Pass the new value to assemble()**

A few lines below (where `assemble()` is invoked around line 763), add `compact_markdown=compact_markdown,` to the call:

```python
    system_prompt = await assemble(
        user_id=user_id,
        persona_id=persona_id,
        model_unique_id=model_unique_id,
        project_id=session.get("project_id"),
        supports_reasoning=supports_reasoning,
        extras=extras,
        compact_markdown=compact_markdown,
    )
```

- [ ] **Step 4: Verify syntax**

Run: `uv run python -m py_compile backend/modules/chat/_orchestrator.py`
Expected: exit code 0.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/chat/_orchestrator.py
git commit -m "Slice messages by compaction tail-start in run_inference"
```

---

### Task 4.3: CompletionRequest.compact_anchor_index

**Files:**
- Modify: `shared/dtos/inference.py`

- [ ] **Step 1: Add the field**

In `shared/dtos/inference.py`, append at the bottom of the `CompletionRequest` class body (after `anthropic_cache_ttl`):

```python
    # Position (0-based index into ``messages``) of the first tail message
    # after a compaction. When set, the Anthropic-cache marker strategy
    # places its 2nd marker here instead of at the heuristic block boundary,
    # so the System + Compact-Anchor prefix is held in cache for 1h between
    # turns of an unchanged checkpoint.
    compact_anchor_index: int | None = None
```

- [ ] **Step 2: Verify syntax**

Run: `uv run python -m py_compile shared/dtos/inference.py`
Expected: exit code 0.

- [ ] **Step 3: Commit**

```bash
git add shared/dtos/inference.py
git commit -m "Add compact_anchor_index to CompletionRequest"
```

---

### Task 4.4: compute_cache_markers compact_anchor parameter

**Files:**
- Modify: `backend/modules/llm/_adapters/_anthropic_cache.py`
- Modify: `backend/tests/modules/llm/adapters/test_anthropic_cache.py`

- [ ] **Step 1: Write the failing tests first**

Append to `backend/tests/modules/llm/adapters/test_anthropic_cache.py`:

```python
def test_compact_anchor_replaces_block_boundary():
    # 20 messages — block-boundary would land at index 15 (BLOCK_SIZE=8).
    # With compact_anchor_index=3, marker 2 should sit at index 3 instead.
    msgs = [
        CompletionMessage(
            role=("system" if i == 0 else "user" if i % 2 else "assistant"),
            content=[ContentPart(type="text", text=f"m{i}")],
        )
        for i in range(20)
    ]
    result = compute_cache_markers(msgs, "5m", compact_anchor_index=3)
    indices = sorted(m.message_index for m in result)
    # Expect: system(0), compact-anchor(3), rolling-tail(18)
    assert indices == [0, 3, 18]
    by_idx = {m.message_index: m for m in result}
    assert by_idx[0].ttl == "1h"
    assert by_idx[3].ttl == "1h"
    assert by_idx[18].ttl == "5m"


def test_compact_anchor_none_keeps_block_boundary():
    msgs = [
        CompletionMessage(
            role=("system" if i == 0 else "user" if i % 2 else "assistant"),
            content=[ContentPart(type="text", text=f"m{i}")],
        )
        for i in range(20)
    ]
    result = compute_cache_markers(msgs, "5m", compact_anchor_index=None)
    indices = sorted(m.message_index for m in result)
    # Block-boundary behaviour preserved when no anchor set.
    assert 15 in indices  # last 8-aligned boundary < n-1
```

- [ ] **Step 2: Run — expect TypeError**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_anthropic_cache.py -v`
Expected: 2 new tests fail (unexpected keyword argument).

- [ ] **Step 3: Extend the function**

In `backend/modules/llm/_adapters/_anthropic_cache.py`, update `compute_cache_markers`:

```python
def compute_cache_markers(
    messages: list[CompletionMessage],
    ttl: CacheTtl,
    *,
    compact_anchor_index: int | None = None,
) -> list[CacheMarker]:
    """Compute marker positions for an Anthropic-compatible request.

    When ``compact_anchor_index`` is set (i.e. the session carries an
    active compaction checkpoint), marker 2 sits at that index instead
    of the heuristic block boundary. See spec
    devdocs/specs/2026-05-15-compact-and-continue-design.md §6.10.
    """
    if ttl == "off" or not messages:
        return []

    markers: list[CacheMarker] = []

    if messages[0].role == "system":
        markers.append(CacheMarker(message_index=0, ttl="1h"))

    if compact_anchor_index is not None and 0 <= compact_anchor_index < len(messages):
        if not any(m.message_index == compact_anchor_index for m in markers):
            markers.append(CacheMarker(message_index=compact_anchor_index, ttl="1h"))
    else:
        n = len(messages)
        last_block_end = (n // BLOCK_SIZE) * BLOCK_SIZE - 1
        if last_block_end > 0 and last_block_end < n - 1:
            if not any(m.message_index == last_block_end for m in markers):
                markers.append(
                    CacheMarker(message_index=last_block_end, ttl="1h"),
                )

    n = len(messages)
    if n >= 2:
        tail_index = n - 2
        if tail_index > 0 and not any(
            m.message_index == tail_index for m in markers
        ):
            markers.append(CacheMarker(message_index=tail_index, ttl=ttl))

    return markers
```

- [ ] **Step 4: Re-run the full file**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_anthropic_cache.py -v`
Expected: all tests (existing + 2 new) pass.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_anthropic_cache.py backend/tests/modules/llm/adapters/test_anthropic_cache.py
git commit -m "Add compact_anchor_index to Anthropic cache marker strategy"
```

---

### Task 4.5: Adapter wiring (openrouter + nano-gpt)

**Files:**
- Modify: `backend/modules/llm/_adapters/_openrouter_http.py`
- Modify: `backend/modules/llm/_adapters/_nano_gpt_http.py`

- [ ] **Step 1: openrouter — pipe the new field**

In `backend/modules/llm/_adapters/_openrouter_http.py`, find the `compute_cache_markers(...)` call (around line 385). Change:

```python
        for marker in compute_cache_markers(
            request.messages, request.anthropic_cache_ttl,
        ):
```

to:

```python
        for marker in compute_cache_markers(
            request.messages,
            request.anthropic_cache_ttl,
            compact_anchor_index=request.compact_anchor_index,
        ):
```

- [ ] **Step 2: nano-gpt — same change**

In `backend/modules/llm/_adapters/_nano_gpt_http.py`, find the analogous `compute_cache_markers` call (around line 337) and add the same `compact_anchor_index=request.compact_anchor_index,` argument.

- [ ] **Step 3: Verify both files**

Run: `uv run python -m py_compile backend/modules/llm/_adapters/_openrouter_http.py backend/modules/llm/_adapters/_nano_gpt_http.py`
Expected: exit code 0.

- [ ] **Step 4: Run existing adapter tests to confirm no regression**

Run: `uv run pytest backend/tests/modules/llm/adapters/ -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_openrouter_http.py backend/modules/llm/_adapters/_nano_gpt_http.py
git commit -m "Pipe compact_anchor_index through OpenRouter and nano-gpt adapters"
```

---

### Task 4.6: Pipe compact_anchor_index from run_inference

**Files:**
- Modify: `backend/modules/chat/_orchestrator.py`

- [ ] **Step 1: Locate where the CompletionRequest is built**

In `backend/modules/chat/_orchestrator.py`, find the `CompletionRequest(...)` instantiation that follows the message-list assembly. Look for `anthropic_cache_ttl=` to find the right spot.

- [ ] **Step 2: Compute the anchor index just before the request is built**

After the final `messages` list (the one passed into `CompletionRequest`) is assembled, add:

```python
    # The compact anchor is the index of the first tail message in the
    # final messages list. messages[0] is the system prompt, so the
    # earliest possible anchor is index 1.
    compact_anchor_index_for_cache: int | None = None
    if compact_markdown is not None and len(messages) > 1:
        compact_anchor_index_for_cache = 1
```

- [ ] **Step 3: Pass it into CompletionRequest**

In the `CompletionRequest(...)` call, add:

```python
        compact_anchor_index=compact_anchor_index_for_cache,
```

right alongside the existing `anthropic_cache_ttl=...` argument.

- [ ] **Step 4: Verify syntax**

Run: `uv run python -m py_compile backend/modules/chat/_orchestrator.py`
Expected: exit code 0.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/chat/_orchestrator.py
git commit -m "Forward compact anchor index to Anthropic cache strategy"
```

---

## Phase 5: Edit Protection

### Task 5.1: handle_chat_edit guard

**Files:**
- Modify: `backend/modules/chat/_handlers_ws.py`

- [ ] **Step 1: Locate handle_chat_edit**

Open `backend/modules/chat/_handlers_ws.py`. Find `async def handle_chat_edit` (search for the function name). Identify where the function loads the session and where it loads the target message.

- [ ] **Step 2: Add the guard**

Immediately after the function loads `session` and the target `message`, before any DB write, add:

```python
    checkpoints = session.get("compaction_checkpoints") or []
    if checkpoints:
        latest = checkpoints[-1]
        tail_start_msg = await repo.get_message(latest["tail_start_message_id"])
        if (
            tail_start_msg is not None
            and message["created_at"] < tail_start_msg["created_at"]
        ):
            from shared.events.system import ErrorEvent
            await event_bus.publish(
                Topics.ERROR,
                ErrorEvent(
                    type="error",
                    correlation_id=correlation_id,
                    error_code="edit_before_compact",
                    recoverable=False,
                    user_message=(
                        "This message is part of a compact snapshot and "
                        "can no longer be edited. Start a new session if "
                        "you need to go back further."
                    ),
                    detail=None,
                ),
                scope=f"session:{session['_id']}",
                target_user_ids=[user_id],
                correlation_id=correlation_id,
            )
            return
```

**Note for the implementing subagent:** the exact `ErrorEvent` schema and `event_bus.publish` keyword arguments may differ — check the surrounding code (existing error emissions in the same file) and align with the file's conventions. The intent: stop the edit and surface a non-recoverable error to the user.

- [ ] **Step 3: Verify syntax**

Run: `uv run python -m py_compile backend/modules/chat/_handlers_ws.py`
Expected: exit code 0.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/chat/_handlers_ws.py
git commit -m "Block edits to messages before the latest compaction tail"
```

---

### Task 5.2: handle_chat_regenerate guard

**Files:**
- Modify: `backend/modules/chat/_handlers_ws.py`

- [ ] **Step 1: Check whether regenerate operates on a specific message**

In the same file, find `handle_chat_regenerate` (or similar). If it regenerates the most recent assistant message only, no guard is needed — regenerating the head of the tail is fine. If it accepts a `message_id` parameter and could target a source-range message, add the same guard pattern from 5.1.

- [ ] **Step 2: Add guard only if needed**

If a guard is added, mirror the 5.1 block exactly (substituting the local variable names). If not, leave the function untouched and note this in the commit message.

- [ ] **Step 3: Verify syntax**

Run: `uv run python -m py_compile backend/modules/chat/_handlers_ws.py`
Expected: exit code 0.

- [ ] **Step 4: Commit**

```bash
git add backend/modules/chat/_handlers_ws.py
git commit -m "Apply compaction edit-guard to regenerate path (or document no-op)"
```

---

## Phase 6: Trigger Handler

### Task 6.1: handle_chat_compaction_request — basic validation

**Files:**
- Modify: `backend/modules/chat/_handlers_ws.py`

- [ ] **Step 1: Add the handler skeleton**

At the bottom of `_handlers_ws.py`, add:

```python
async def handle_chat_compaction_request(
    *,
    payload: dict,
    user_id: str,
    event_bus,
    correlation_id: str,
) -> None:
    """Trigger a chat compaction job. See spec §6.1."""
    from backend.database import get_db, get_redis
    from backend.modules.chat._repository import ChatRepository

    session_id = payload.get("session_id")
    if not session_id:
        return

    db = get_db()
    repo = ChatRepository(db)
    session = await repo.get_session_by_id(session_id, user_id)
    if session is None:
        return  # ownership / not-found — silent

    # Minimum-size check
    total_messages = await repo.count_messages(session_id)
    total_tokens = int(session.get("context_used_tokens") or 0)
    if total_messages <= 12 or total_tokens < 4000:
        await _emit_compaction_failed(
            event_bus, session_id, correlation_id, user_id,
            error_code="too_small", recoverable=False,
            user_message="Conversation too short to compact yet.",
        )
        return

    # Lower threshold (30%)
    fill = float(session.get("context_fill_percentage") or 0.0)
    if fill < 0.30:
        await _emit_compaction_failed(
            event_bus, session_id, correlation_id, user_id,
            error_code="below_threshold", recoverable=False,
            user_message="Conversation is not large enough to benefit from compaction yet.",
        )
        return
```

Place the `_emit_compaction_failed` helper above it (or alongside other helpers in the file):

```python
async def _emit_compaction_failed(
    event_bus, session_id, correlation_id, user_id,
    *, error_code, user_message, recoverable,
):
    from shared.events.chat import ChatCompactionFailedEvent
    from datetime import datetime, UTC
    await event_bus.publish(
        Topics.CHAT_COMPACTION_FAILED,
        ChatCompactionFailedEvent(
            session_id=session_id,
            correlation_id=correlation_id,
            error_code=error_code,
            user_message=user_message,
            recoverable=recoverable,
            timestamp=datetime.now(UTC),
        ),
        scope=f"session:{session_id}",
        target_user_ids=[user_id],
        correlation_id=correlation_id,
    )
```

**Note for the implementing subagent:** if `count_messages` does not exist on `ChatRepository`, add it as a thin wrapper around `self._messages.count_documents({"session_id": session_id})`.

- [ ] **Step 2: Verify syntax**

Run: `uv run python -m py_compile backend/modules/chat/_handlers_ws.py`
Expected: exit code 0.

- [ ] **Step 3: Commit**

```bash
git add backend/modules/chat/_handlers_ws.py
git commit -m "Add chat compaction request handler — basic validation"
```

---

### Task 6.2: Redis lock acquire/release

**Files:**
- Modify: `backend/modules/chat/_handlers_ws.py`

- [ ] **Step 1: Add lock acquisition after the threshold checks**

In `handle_chat_compaction_request`, after the `fill < 0.30` check but before any further logic, add:

```python
    redis = get_redis()
    lock_key = f"compaction:lock:{session_id}"
    acquired = await redis.set(lock_key, correlation_id, nx=True, ex=600)
    if not acquired:
        await _emit_compaction_failed(
            event_bus, session_id, correlation_id, user_id,
            error_code="already_running", recoverable=True,
            user_message="A compaction is already running for this conversation.",
        )
        return
```

(The lock is released by the job handler in `finally`. The trigger handler does NOT release on success.)

- [ ] **Step 2: Verify syntax**

Run: `uv run python -m py_compile backend/modules/chat/_handlers_ws.py`
Expected: exit code 0.

- [ ] **Step 3: Commit**

```bash
git add backend/modules/chat/_handlers_ws.py
git commit -m "Acquire Redis lock before submitting compaction job"
```

---

### Task 6.3: Pre-flight check + source/tail computation

**Files:**
- Modify: `backend/modules/chat/_handlers_ws.py`

- [ ] **Step 1: After the lock, compute source/tail and run pre-flight**

Add after the lock acquisition:

```python
    from backend.modules.chat._compaction import (
        COMPACTION_SYSTEM_PROMPT_TOKENS,
        COMPACTION_MAX_OUTPUT_TOKENS,
        COMPACTION_SAFETY_MARGIN,
        determine_tail_start_index,
        select_source_range,
        sanitise_source,
    )
    from backend.modules.llm import get_effective_context_window

    model_unique_id = (
        session.get("model_unique_id") or ""
    )
    if not model_unique_id:
        # Fall back to persona's model
        from backend.modules.persona import get_persona
        persona = await get_persona(session.get("persona_id"), user_id)
        model_unique_id = (persona or {}).get("model_unique_id", "")

    model_context = await get_effective_context_window(user_id, model_unique_id) or 8192

    all_messages = await repo.list_messages(session_id)

    checkpoints = session.get("compaction_checkpoints") or []
    prev_checkpoint_id = checkpoints[-1]["id"] if checkpoints else None
    prev_tail_start_id = (
        checkpoints[-1]["tail_start_message_id"] if checkpoints else None
    )

    tail_start_idx = determine_tail_start_index(
        all_messages, model_context=model_context,
    )
    source_raw, tail_msgs = select_source_range(
        all_messages,
        tail_start_index=tail_start_idx,
        prev_tail_start_id=prev_tail_start_id,
    )
    source_msgs = sanitise_source(source_raw)
    source_tokens = sum(int(m.get("token_count") or 0) for m in source_msgs)

    overhead = (
        COMPACTION_SYSTEM_PROMPT_TOKENS
        + COMPACTION_MAX_OUTPUT_TOKENS
        + COMPACTION_SAFETY_MARGIN
    )
    if source_tokens + overhead > model_context:
        await redis.delete(lock_key)
        await _emit_compaction_failed(
            event_bus, session_id, correlation_id, user_id,
            error_code="compaction_source_too_large", recoverable=False,
            user_message=(
                "Conversation is too large for the current model to compact. "
                "Switch to a model with a larger context window or start "
                "a new session."
            ),
        )
        return
```

- [ ] **Step 2: Verify syntax**

Run: `uv run python -m py_compile backend/modules/chat/_handlers_ws.py`
Expected: exit code 0.

- [ ] **Step 3: Commit**

```bash
git add backend/modules/chat/_handlers_ws.py
git commit -m "Run pre-flight check before submitting compaction job"
```

---

### Task 6.4: Submit job + emit started event

**Files:**
- Modify: `backend/modules/chat/_handlers_ws.py`

- [ ] **Step 1: Append the submission + event emission**

At the end of `handle_chat_compaction_request` (after the pre-flight check), add:

```python
    from backend.jobs import submit_job
    from backend.jobs._models import JobType
    from shared.events.chat import ChatCompactionStartedEvent
    from datetime import datetime, UTC

    estimated_after = max(500, int(source_tokens * 0.08))

    await submit_job(
        job_type=JobType.CHAT_COMPACTION,
        user_id=user_id,
        model_unique_id=model_unique_id,
        payload={
            "session_id": session_id,
            "correlation_id": correlation_id,
            "prev_checkpoint_id": prev_checkpoint_id,
        },
        correlation_id=correlation_id,
    )

    await event_bus.publish(
        Topics.CHAT_COMPACTION_STARTED,
        ChatCompactionStartedEvent(
            session_id=session_id,
            correlation_id=correlation_id,
            tokens_before=source_tokens,
            estimated_tokens_after=estimated_after,
            tail_message_count=len(tail_msgs),
            timestamp=datetime.now(UTC),
        ),
        scope=f"session:{session_id}",
        target_user_ids=[user_id],
        correlation_id=correlation_id,
    )
```

**Note for the implementing subagent:** The actual `submit_job` entry point is `backend.jobs.submit` (re-exported as `submit_job`?). Adjust the import based on what the package's `__init__.py` exposes. The fallback is `from backend.jobs._submit import submit as submit_job` plus the same call.

- [ ] **Step 2: Verify syntax**

Run: `uv run python -m py_compile backend/modules/chat/_handlers_ws.py`
Expected: exit code 0.

- [ ] **Step 3: Commit**

```bash
git add backend/modules/chat/_handlers_ws.py
git commit -m "Submit chat compaction job and emit started event"
```

---

### Task 6.5: WS-router wiring

**Files:**
- Modify: `backend/ws/router.py` (or the file that maps incoming WS event types to handlers — verify the actual location)

- [ ] **Step 1: Find the router map**

Run `grep -n "chat.compaction\|chat\\.regenerate\|chat\\.edit" backend/ws/router.py` (and `grep -rn "CHAT_REGENERATE\|handle_chat_edit" backend/ws/` if needed) to locate the dispatch table.

- [ ] **Step 2: Add the dispatch entry**

In the dispatch map, add a mapping from `"chat.compaction.request"` (or `Topics.CHAT_COMPACTION_REQUEST`) to `handle_chat_compaction_request`:

```python
    "chat.compaction.request": handle_chat_compaction_request,
```

If the router uses a different shape (e.g. a registration decorator or a class-based dispatch), follow that pattern instead. The intent: when the client sends a `{"type": "chat.compaction.request", ...}` over the WebSocket, the new handler runs.

- [ ] **Step 3: Verify syntax**

Run: `uv run python -m py_compile backend/ws/router.py`
Expected: exit code 0.

- [ ] **Step 4: Commit**

```bash
git add backend/ws/router.py
git commit -m "Route chat.compaction.request to its handler"
```

---

## Phase 7: Frontend Session Store + WS

### Task 7.1: TS DTOs

**Files:**
- Modify: `frontend/src/types/chat.ts` (or wherever ChatSession-related types live — `grep -rn "compaction\|context_fill_percentage" frontend/src/types/` to locate)

- [ ] **Step 1: Add the checkpoint type**

Add to the appropriate types file:

```typescript
export interface CompactionCheckpoint {
  id: string
  created_at: string
  model_unique_id: string
  summary_markdown: string
  last_message_id_before: string
  tail_start_message_id: string
  tokens_before: number
  tokens_after: number
  tail_token_count: number
  prev_checkpoint_id: string | null
}
```

- [ ] **Step 2: Extend the ChatSession type**

In the same file (or the file that defines `ChatSession`), add:

```typescript
  compaction_checkpoints: CompactionCheckpoint[]
```

to the `ChatSession` interface (default to an empty array on the store-loading path).

- [ ] **Step 3: Verify**

Run: `pnpm -C frontend run build`
Expected: exit code 0.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/chat.ts
git commit -m "Add CompactionCheckpoint type to frontend"
```

---

### Task 7.2: chatStore — checkpoints and helpers

**Files:**
- Modify: `frontend/src/stores/chatStore.ts` (or equivalent — locate via `grep -rn "compaction\|context_fill" frontend/src/stores/` and `grep -rn "context_status" frontend/src/features/chat/store* frontend/src/stores/`)

- [ ] **Step 1: Add a helper action**

Add a new action on the store that appends a checkpoint to a session:

```typescript
  appendCompactionCheckpoint(sessionId: string, checkpoint: CompactionCheckpoint) {
    const session = this.sessions.find((s) => s.id === sessionId)
    if (!session) return
    session.compaction_checkpoints = [
      ...(session.compaction_checkpoints || []),
      checkpoint,
    ]
  },
```

Adapt the action's exact shape to whatever store library is in use (Zustand, Pinia-style, plain Redux, etc.) — the intent: an idempotent append that surfaces a re-render to subscribers.

- [ ] **Step 2: Verify**

Run: `pnpm -C frontend run build`
Expected: exit code 0.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/stores/chatStore.ts
git commit -m "Add appendCompactionCheckpoint action to chat store"
```

---

### Task 7.3: useChatStream subscriptions

**Files:**
- Modify: `frontend/src/features/chat/useChatStream.ts`

- [ ] **Step 1: Add handlers for the four topics**

Inside `handleChatEvent` (around lines 36–150), add cases:

```typescript
    case 'chat.compaction.started': {
      setCompactionLoading(true, event.correlation_id)
      break
    }
    case 'chat.compaction.progress': {
      // Optional spinner-text update; MVP just keeps loading state.
      break
    }
    case 'chat.compaction.completed': {
      appendCompactionCheckpoint(event.session_id, event.checkpoint)
      setCompactionLoading(false)
      showSuccessToast(event)
      break
    }
    case 'chat.compaction.failed': {
      setCompactionLoading(false)
      showFailureToast(event)
      break
    }
```

The `setCompactionLoading`, `showSuccessToast`, `showFailureToast` symbols are introduced in Phase 8/11 — leave as imports from a new `./compaction.ts` module that those tasks create. For now, declare them inline as stubs above the handler:

```typescript
const setCompactionLoading = (_loading: boolean, _correlationId?: string) => { /* wired in Phase 8 */ }
const showSuccessToast = (_e: any) => { /* wired in Phase 11 */ }
const showFailureToast = (_e: any) => { /* wired in Phase 11 */ }
```

- [ ] **Step 2: Verify**

Run: `pnpm -C frontend run build`
Expected: exit code 0 (stubs are no-ops; TypeScript should accept the event shape once you've added rough types).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/chat/useChatStream.ts
git commit -m "Subscribe useChatStream to compaction events"
```

---

## Phase 8: Sparkly Button

### Task 8.1: useCompactionState hook

**Files:**
- Create: `frontend/src/features/chat/compaction/useCompactionState.ts`

- [ ] **Step 1: Implement the hook**

```typescript
import { useMemo } from 'react'
import type { ChatSession } from '../../../types/chat'

export type CompactButtonVisibility =
  | 'hidden_too_short'
  | 'overflow_only'
  | 'subtle'
  | 'sparkle'
  | 'warning'
  | 'disabled_too_big'

export interface CompactionState {
  visibility: CompactButtonVisibility
  tooltip: string
  showSparkle: boolean
  modalHintTrigger: number    // increments when state crosses an alert threshold
  canTrigger: boolean
}

export function useCompactionState(session: ChatSession, modelContext: number): CompactionState {
  return useMemo(() => {
    const totalMessages = session.message_count ?? 0
    const totalTokens = session.context_used_tokens ?? 0
    const fill = session.context_fill_percentage ?? 0

    const minSize = totalMessages > 12 && totalTokens > 4000
    if (!minSize) {
      return {
        visibility: 'hidden_too_short',
        tooltip: 'Conversation too short to compact yet',
        showSparkle: false,
        modalHintTrigger: 0,
        canTrigger: false,
      }
    }

    if (fill < 0.30) {
      return {
        visibility: 'overflow_only',
        tooltip: 'Compact this conversation',
        showSparkle: false,
        modalHintTrigger: 0,
        canTrigger: false,    // < 30 %: still in overflow only — button greyed in top-bar
      }
    }
    if (fill < 0.60) {
      return {
        visibility: 'overflow_only',
        tooltip: 'Compact this conversation',
        showSparkle: false,
        modalHintTrigger: 0,
        canTrigger: true,
      }
    }
    if (fill < 0.75) {
      return {
        visibility: 'subtle',
        tooltip: 'Compact this conversation?',
        showSparkle: false,
        modalHintTrigger: 0,
        canTrigger: true,
      }
    }
    if (fill < 0.90) {
      return {
        visibility: 'sparkle',
        tooltip: 'Context is filling up — compact soon',
        showSparkle: true,
        modalHintTrigger: 1,
        canTrigger: true,
      }
    }
    return {
      visibility: 'warning',
      tooltip: 'Compaction may fail — consider switching to a larger model',
      showSparkle: true,
      modalHintTrigger: 2,
      canTrigger: true,
    }
  }, [session, modelContext])
}
```

- [ ] **Step 2: Verify**

Run: `pnpm -C frontend run build`
Expected: exit code 0.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/chat/compaction/useCompactionState.ts
git commit -m "Add useCompactionState hook for sparkly button"
```

---

### Task 8.2: SparkleCompactButton component

**Files:**
- Create: `frontend/src/features/chat/compaction/SparkleCompactButton.tsx`

- [ ] **Step 1: Create the component**

```tsx
import { useCompactionState } from './useCompactionState'
import type { ChatSession } from '../../../types/chat'

interface Props {
  session: ChatSession
  modelContext: number
  isLoading: boolean
  onClick: () => void
}

export function SparkleCompactButton({ session, modelContext, isLoading, onClick }: Props) {
  const state = useCompactionState(session, modelContext)

  if (state.visibility === 'hidden_too_short' || state.visibility === 'overflow_only') {
    return null
  }
  if (state.visibility === 'disabled_too_big') {
    return (
      <button disabled title={state.tooltip} className="opacity-50 cursor-not-allowed">
        ✨
      </button>
    )
  }

  const sparkleCls = state.showSparkle ? 'animate-pulse' : ''
  const warnCls = state.visibility === 'warning' ? 'text-orange-400' : ''

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={isLoading}
      title={state.tooltip}
      className={`px-2 py-1 rounded ${sparkleCls} ${warnCls}`}
    >
      {isLoading ? '✨ Compacting…' : '✨'}
    </button>
  )
}
```

Adapt Tailwind classes to match the project's existing top-bar styling — the intent: a small icon button with subtle pulse animation when `showSparkle` is true and an orange tint when state is `warning`.

- [ ] **Step 2: Verify**

Run: `pnpm -C frontend run build`
Expected: exit code 0.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/chat/compaction/SparkleCompactButton.tsx
git commit -m "Add SparkleCompactButton component"
```

---

### Task 8.3: CompactConfirmCard component

**Files:**
- Create: `frontend/src/features/chat/compaction/CompactConfirmCard.tsx`

- [ ] **Step 1: Create the component**

```tsx
interface Props {
  contextUsed: number
  contextMax: number
  onConfirm: () => void
  onCancel: () => void
}

export function CompactConfirmCard({ contextUsed, contextMax, onConfirm, onCancel }: Props) {
  const fillPct = Math.round((contextUsed / contextMax) * 100)
  const estimatedAfter = Math.max(500, Math.round(contextUsed * 0.08))

  return (
    <div className="p-4 rounded-lg border bg-surface">
      <p className="text-sm">
        {contextUsed.toLocaleString()} / {contextMax.toLocaleString()} tokens, {fillPct}%
      </p>
      <p className="text-sm text-muted">
        After compact: ~{estimatedAfter.toLocaleString()} tokens
      </p>
      <p className="text-sm mt-2">
        The last 6 turns stay verbatim; everything before is condensed into a briefing.
      </p>
      <div className="mt-3 flex gap-2">
        <button onClick={onConfirm} className="btn-primary">Compact</button>
        <button onClick={onCancel} className="btn-secondary">Cancel</button>
      </div>
    </div>
  )
}
```

Adapt class names to the project's existing button/card design tokens.

- [ ] **Step 2: Verify**

Run: `pnpm -C frontend run build`
Expected: exit code 0.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/chat/compaction/CompactConfirmCard.tsx
git commit -m "Add CompactConfirmCard component"
```

---

### Task 8.4: Desktop placement in ChatView top-bar

**Files:**
- Modify: `frontend/src/features/chat/ChatView.tsx`

- [ ] **Step 1: Locate the top-bar block**

In `ChatView.tsx`, find the desktop top-bar around line 1187 — specifically the JSX that renders `<ContextStatusPill ...>`.

- [ ] **Step 2: Add the button and confirm-card popover**

Right after the `<ContextStatusPill>` JSX, add:

```tsx
        <SparkleCompactButton
          session={session}
          modelContext={contextMax}
          isLoading={compactionLoading}
          onClick={() => setShowCompactConfirm(true)}
        />
        {showCompactConfirm && (
          <CompactConfirmCard
            contextUsed={session.context_used_tokens ?? 0}
            contextMax={contextMax}
            onConfirm={() => {
              setShowCompactConfirm(false)
              sendCompactionRequest(session.id)
            }}
            onCancel={() => setShowCompactConfirm(false)}
          />
        )}
```

You'll also need to add local state at the top of the component:

```tsx
  const [showCompactConfirm, setShowCompactConfirm] = useState(false)
  const [compactionLoading, setCompactionLoading] = useState(false)
```

and the helper `sendCompactionRequest(sessionId)` — this calls the existing WS-send abstraction with `{ type: 'chat.compaction.request', session_id, correlation_id: uuid() }`. Find an existing event-send helper (e.g. for chat.edit) and mirror its shape.

- [ ] **Step 3: Verify**

Run: `pnpm -C frontend run build`
Expected: exit code 0.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/chat/ChatView.tsx
git commit -m "Add sparkly compact button to desktop top-bar"
```

---

### Task 8.5: Mobile placement in indicator row

**Files:**
- Modify: `frontend/src/features/chat/ChatView.tsx`

- [ ] **Step 1: Locate the mobile indicator row**

Around line 1222 — the compact indicator row used on small viewports.

- [ ] **Step 2: Insert the icon-only button + bottom-sheet variant**

Add the `<SparkleCompactButton>` (same component) and gate the confirm UI behind a mobile-detection helper. The confirm UI on mobile should be a bottom-sheet rather than an inline card — wrap `<CompactConfirmCard>` in whatever existing bottom-sheet primitive the project provides (search for `BottomSheet` or `lg:` breakpoint usages to find existing pattern).

- [ ] **Step 3: Verify**

Run: `pnpm -C frontend run build`
Expected: exit code 0.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/chat/ChatView.tsx
git commit -m "Add sparkly compact button to mobile indicator row"
```

---

### Task 8.6: Loading overlay for input area

**Files:**
- Modify: `frontend/src/features/chat/ChatView.tsx`

- [ ] **Step 1: Wire compactionLoading into the existing input-locked path**

When `compactionLoading` is true, the input composer should be disabled and an overlay should appear above it with the text:

```
Compacting your conversation — one moment
```

Find the existing send-pending lock (the one that disables the composer during in-flight assistant responses) and reuse the same DOM pattern — adapt label and conditional. The state is set true on `chat.compaction.started` and cleared on `chat.compaction.completed` / `chat.compaction.failed`.

- [ ] **Step 2: Wire the actual `setCompactionLoading` from `useChatStream`**

Update the stub in `useChatStream.ts` (added in Task 7.3) to call a real setter exposed by the parent component or a shared store slice. Replace:

```typescript
const setCompactionLoading = (_loading: boolean, _correlationId?: string) => { /* wired in Phase 8 */ }
```

with the real setter. Common patterns: lift the state into a shared Zustand slice, or pass a setter down via context.

- [ ] **Step 3: Verify**

Run: `pnpm -C frontend run build`
Expected: exit code 0.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/chat/ChatView.tsx frontend/src/features/chat/useChatStream.ts
git commit -m "Wire compaction loading overlay into ChatView input area"
```

---

## Phase 9: Suggest Toast

### Task 9.1: Threshold-cross detector hook

**Files:**
- Create: `frontend/src/features/chat/compaction/useSuggestToast.ts`

- [ ] **Step 1: Implement the detector**

```typescript
import { useEffect, useRef } from 'react'
import type { ChatSession } from '../../../types/chat'

export function useSuggestToast(
  session: ChatSession | undefined,
  isContinuousVoice: boolean,
  onCross: () => void,
) {
  const lastSeen = useRef<number>(0)
  useEffect(() => {
    if (!session) return
    const current = session.context_fill_percentage ?? 0
    const prev = lastSeen.current
    lastSeen.current = current
    if (isContinuousVoice) return
    if (prev < 0.60 && current >= 0.60) {
      onCross()
    }
  }, [session?.context_fill_percentage, isContinuousVoice])
}
```

- [ ] **Step 2: Verify**

Run: `pnpm -C frontend run build`
Expected: exit code 0.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/chat/compaction/useSuggestToast.ts
git commit -m "Add suggest-toast threshold-cross detector"
```

---

### Task 9.2: SuggestCompactToast component + wiring

**Files:**
- Create: `frontend/src/features/chat/compaction/SuggestCompactToast.tsx`
- Modify: `frontend/src/features/chat/ChatView.tsx`

- [ ] **Step 1: Create the toast component**

```tsx
interface Props {
  fillPct: number
  onCompact: () => void
  onLater: () => void
}

export function SuggestCompactToast({ fillPct, onCompact, onLater }: Props) {
  return (
    <div className="toast">
      <p>Conversation is at {Math.round(fillPct * 100)}% context. Compact now?</p>
      <button onClick={onCompact}>Compact</button>
      <button onClick={onLater}>Later</button>
    </div>
  )
}
```

Adapt to the project's toast primitive. If the project uses a global toast queue, render through that instead of returning JSX directly.

- [ ] **Step 2: Wire into ChatView**

In `ChatView.tsx`:

```tsx
  const [showSuggestToast, setShowSuggestToast] = useState(false)
  useSuggestToast(session, isContinuousVoice, () => setShowSuggestToast(true))

  {showSuggestToast && (
    <SuggestCompactToast
      fillPct={session.context_fill_percentage ?? 0}
      onCompact={() => {
        setShowSuggestToast(false)
        sendCompactionRequest(session.id)
      }}
      onLater={() => setShowSuggestToast(false)}
    />
  )}
```

Find `isContinuousVoice` via the existing `usePhase()` hook (it should already be in scope in `ChatView.tsx`).

- [ ] **Step 3: Verify**

Run: `pnpm -C frontend run build`
Expected: exit code 0.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/chat/compaction/SuggestCompactToast.tsx frontend/src/features/chat/ChatView.tsx
git commit -m "Show suggest-compact toast on first 60% cross"
```

---

## Phase 10: Compacted Marker + Drawer

### Task 10.1: TimelineEntry 'compacted' kind type

**Files:**
- Modify: the file that defines the `TimelineEntry` discriminated union (locate via `grep -rn "kind: 'knowledge_search'\|kind: 'compacted'" frontend/src/features/chat/`)

- [ ] **Step 1: Add the variant**

```typescript
| {
    kind: 'compacted'
    checkpoint: CompactionCheckpoint
  }
```

- [ ] **Step 2: Verify**

Run: `pnpm -C frontend run build`
Expected: exit code 0.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/chat/
git commit -m "Add 'compacted' kind to TimelineEntry union"
```

---

### Task 10.2: CompactedMarkerPill component

**Files:**
- Create: `frontend/src/features/chat/compaction/CompactedMarkerPill.tsx`

- [ ] **Step 1: Implement**

```tsx
import type { CompactionCheckpoint } from '../../../types/chat'

interface Props {
  checkpoint: CompactionCheckpoint
  onOpen: () => void
}

function formatTokens(n: number): string {
  if (n >= 1000) return `${Math.round(n / 1000)}k`
  return String(n)
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

export function CompactedMarkerPill({ checkpoint, onOpen }: Props) {
  return (
    <div className="flex items-center my-4">
      <hr className="flex-1 border-t" />
      <button
        onClick={onOpen}
        className="mx-3 px-3 py-1 rounded-full text-xs font-mono bg-surface border"
      >
        ✨ Compacted · {formatTime(checkpoint.created_at)} ·{' '}
        {formatTokens(checkpoint.tokens_before)} → {formatTokens(checkpoint.tokens_after)} tokens
      </button>
      <hr className="flex-1 border-t" />
    </div>
  )
}
```

- [ ] **Step 2: Verify**

Run: `pnpm -C frontend run build`
Expected: exit code 0.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/chat/compaction/CompactedMarkerPill.tsx
git commit -m "Add CompactedMarkerPill component"
```

---

### Task 10.3: MessageList renderer wiring

**Files:**
- Modify: `frontend/src/features/chat/MessageList.tsx`

- [ ] **Step 1: Inject compaction markers into the timeline**

In `MessageList.tsx`, before rendering messages, weave compaction checkpoints into the timeline at the position of their `tail_start_message_id`:

```tsx
// Build a Map<messageId, CompactionCheckpoint> so we can insert a marker
// before each message that is the tail-start of a checkpoint.
const checkpointByTailId = new Map<string, CompactionCheckpoint>()
for (const cp of session.compaction_checkpoints ?? []) {
  checkpointByTailId.set(cp.tail_start_message_id, cp)
}
```

In the message-rendering loop (the existing block around lines 94–144), check before rendering each message:

```tsx
const cp = checkpointByTailId.get(message.id)
if (cp) {
  rendered.push(
    <CompactedMarkerPill
      key={`compacted-${cp.id}`}
      checkpoint={cp}
      onOpen={() => setOpenCheckpoint(cp)}
    />,
  )
}
```

Then render the message as usual. Add the `openCheckpoint` state and drawer mount near the top of the component:

```tsx
const [openCheckpoint, setOpenCheckpoint] = useState<CompactionCheckpoint | null>(null)
```

- [ ] **Step 2: Verify**

Run: `pnpm -C frontend run build`
Expected: exit code 0.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/chat/MessageList.tsx
git commit -m "Render compacted markers between source and tail in MessageList"
```

---

### Task 10.4: CompactedSnapshotDrawer (desktop slide-over)

**Files:**
- Create: `frontend/src/features/chat/compaction/CompactedSnapshotDrawer.tsx`

- [ ] **Step 1: Implement the drawer**

```tsx
import ReactMarkdown from 'react-markdown'
import type { CompactionCheckpoint } from '../../../types/chat'

interface Props {
  checkpoint: CompactionCheckpoint | null
  onClose: () => void
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

export function CompactedSnapshotDrawer({ checkpoint, onClose }: Props) {
  if (!checkpoint) return null
  return (
    <aside className="fixed top-0 right-0 h-full w-[480px] bg-surface border-l shadow-xl z-50 flex flex-col">
      <header className="p-4 border-b flex items-start justify-between">
        <div>
          <h3 className="font-semibold">
            Compact snapshot · {formatTime(checkpoint.created_at)} · {checkpoint.model_unique_id.split(':')[1]}
          </h3>
          <p className="text-sm text-muted mt-1">
            Original {checkpoint.tokens_before.toLocaleString()} tokens → Briefing {checkpoint.tokens_after.toLocaleString()} tokens
          </p>
        </div>
        <button onClick={onClose} aria-label="Close">✕</button>
      </header>
      <div className="flex-1 overflow-y-auto p-4 prose prose-invert max-w-none">
        <ReactMarkdown>{checkpoint.summary_markdown}</ReactMarkdown>
      </div>
    </aside>
  )
}
```

If the project doesn't already use `react-markdown`, fall back to a `<pre>` block.

- [ ] **Step 2: Mount the drawer from MessageList**

In `MessageList.tsx`, at the bottom of the JSX, mount:

```tsx
<CompactedSnapshotDrawer
  checkpoint={openCheckpoint}
  onClose={() => setOpenCheckpoint(null)}
/>
```

- [ ] **Step 3: Verify**

Run: `pnpm -C frontend run build`
Expected: exit code 0.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/chat/compaction/CompactedSnapshotDrawer.tsx frontend/src/features/chat/MessageList.tsx
git commit -m "Add desktop slide-over drawer for compaction snapshots"
```

---

### Task 10.5: Mobile bottom-sheet variant

**Files:**
- Modify: `frontend/src/features/chat/compaction/CompactedSnapshotDrawer.tsx`

- [ ] **Step 1: Add a viewport-conditional render**

Inside the component, detect viewport size (use the project's existing `useMediaQuery`-style hook or the `lg:` Tailwind breakpoint pattern that's used elsewhere). For small viewports, render the same content inside a bottom-sheet container instead of a right-side slide-over. Look for `BottomSheet` or `lg:hidden` patterns in the codebase to find the project's convention.

- [ ] **Step 2: Verify**

Run: `pnpm -C frontend run build`
Expected: exit code 0.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/chat/compaction/CompactedSnapshotDrawer.tsx
git commit -m "Add mobile bottom-sheet variant to compaction drawer"
```

---

## Phase 11: Result Toasts

### Task 11.1: Success toast on COMPLETED

**Files:**
- Create: `frontend/src/features/chat/compaction/toasts.ts`
- Modify: `frontend/src/features/chat/useChatStream.ts`

- [ ] **Step 1: Implement the toast helpers**

`frontend/src/features/chat/compaction/toasts.ts`:

```typescript
import type { ChatCompactionCompletedEvent, ChatCompactionFailedEvent } from '../../../types/chat-events'
import { showToast } from '../../../ui/toast'   // adapt to project's toast primitive

function formatTokens(n: number): string {
  if (n >= 1000) return `${Math.round(n / 1000)}k`
  return String(n)
}

export function showCompactionSuccess(event: ChatCompactionCompletedEvent) {
  let message = `✨ Compacted — saved ${formatTokens(event.tokens_saved)} tokens`
  if ((event.truncated_message_count ?? 0) > 0) {
    message += `. Note: the ${event.truncated_message_count} oldest messages didn't fit into the briefing.`
  }
  showToast({ kind: 'success', message, durationMs: 4000 })
}

export function showCompactionFailure(event: ChatCompactionFailedEvent, onRetry: () => void) {
  showToast({
    kind: 'error',
    message: event.user_message,
    durationMs: 8000,
    actions: event.recoverable
      ? [{ label: 'Retry', onClick: onRetry }]
      : [],
  })
}
```

- [ ] **Step 2: Wire into useChatStream**

In `useChatStream.ts`, replace the stub:

```typescript
const showSuccessToast = (_e: any) => { /* wired in Phase 11 */ }
```

with:

```typescript
import { showCompactionSuccess } from './compaction/toasts'
const showSuccessToast = (e: ChatCompactionCompletedEvent) => showCompactionSuccess(e)
```

- [ ] **Step 3: Verify**

Run: `pnpm -C frontend run build`
Expected: exit code 0.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/chat/compaction/toasts.ts frontend/src/features/chat/useChatStream.ts
git commit -m "Show compaction success toast on completed event"
```

---

### Task 11.2: Failure toast with retry

**Files:**
- Modify: `frontend/src/features/chat/useChatStream.ts`

- [ ] **Step 1: Wire the failure handler**

Replace:

```typescript
const showFailureToast = (_e: any) => { /* wired in Phase 11 */ }
```

with:

```typescript
import { showCompactionFailure } from './compaction/toasts'
const showFailureToast = (e: ChatCompactionFailedEvent) => {
  showCompactionFailure(e, () => sendCompactionRequest(e.session_id))
}
```

(Where `sendCompactionRequest` is the same helper the sparkly-button click handler uses. If it lives outside this file, import it.)

- [ ] **Step 2: Verify**

Run: `pnpm -C frontend run build`
Expected: exit code 0.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/chat/useChatStream.ts
git commit -m "Show compaction failure toast with retry action"
```

---

### Task 11.3: 90s soft-timeout on loading overlay

**Files:**
- Modify: `frontend/src/features/chat/ChatView.tsx`

- [ ] **Step 1: Add a timeout effect**

When `compactionLoading` becomes true, start a 90s timer. If a `CHAT_COMPACTION_COMPLETED` or `_FAILED` event clears the state before the timer fires, cancel the timer. If the timer fires while still loading:

```tsx
useEffect(() => {
  if (!compactionLoading) return
  const timer = setTimeout(() => {
    setCompactionLoading(false)
    showToast({
      kind: 'info',
      message:
        "Compaction is taking longer than expected. " +
        "Reload the page if it doesn't complete soon.",
      durationMs: 6000,
    })
  }, 90_000)
  return () => clearTimeout(timer)
}, [compactionLoading])
```

- [ ] **Step 2: Verify**

Run: `pnpm -C frontend run build`
Expected: exit code 0.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/chat/ChatView.tsx
git commit -m "Add 90s soft-timeout to compaction loading overlay"
```

---

## Phase 12: Verification

### Task 12.1: Backend + frontend build sweep

**Files:** none (validation only)

- [ ] **Step 1: Backend syntax sweep**

Run on every Python file we touched:

```bash
uv run python -m py_compile \
  shared/topics.py \
  shared/dtos/chat.py \
  shared/dtos/inference.py \
  shared/events/chat.py \
  backend/jobs/_models.py \
  backend/jobs/_registry.py \
  backend/jobs/handlers/_chat_compaction.py \
  backend/modules/chat/_compaction.py \
  backend/modules/chat/_models.py \
  backend/modules/chat/_repository.py \
  backend/modules/chat/_prompt_assembler.py \
  backend/modules/chat/_orchestrator.py \
  backend/modules/chat/_handlers_ws.py \
  backend/modules/llm/_adapters/_anthropic_cache.py \
  backend/modules/llm/_adapters/_openrouter_http.py \
  backend/modules/llm/_adapters/_nano_gpt_http.py \
  backend/ws/router.py
```

Expected: exit code 0.

- [ ] **Step 2: Host-OK pytest sweep**

```bash
uv run pytest \
  backend/tests/modules/chat/test_session_compaction_field.py \
  backend/tests/modules/chat/test_compaction_tail.py \
  backend/tests/modules/chat/test_compaction_validation.py \
  backend/tests/modules/chat/test_compaction_prompt.py \
  backend/tests/modules/llm/adapters/test_anthropic_cache.py \
  -v
```

Expected: all green.

- [ ] **Step 3: Frontend build**

```bash
pnpm -C frontend run build
```

Expected: clean.

- [ ] **Step 4: Commit if anything was patched during the sweep**

If a syntax fix or import correction is needed, commit it with a message like `Fix build issues found during verification sweep`.

---

### Task 12.2: Manual verification checklist (Chris)

This task is **for the supervising session / Chris** — subagents do not run UI tests.

Run §9 of `devdocs/specs/2026-05-15-compact-and-continue-design.md` end-to-end against a real running instance (Docker stack up, frontend running, fresh MongoDB if needed):

- 9.1 Happy path desktop manual
- 9.2 Happy path suggest-toast
- 9.3 Re-compaction
- 9.4 Mobile (Phone + small viewport)
- 9.5 Edit protection
- 9.6 Pre-flight failure (small-context model)
- 9.7 Source truncation
- 9.8 LLM transport failure
- 9.9 Validation failure with retry
- 9.10 Continuous-voice suppression
- 9.11 Backwards compatibility
- 9.12 Provider switch with active compact
- 9.13 Very short session

Final step: squash the entire compact-and-continue implementation (including the spec + plan commits) into a single commit on master, per the user's "one spec = one commit" preference.
