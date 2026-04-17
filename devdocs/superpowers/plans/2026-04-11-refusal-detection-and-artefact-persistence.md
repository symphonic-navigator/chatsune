# Refusal Detection & Artefact Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship refusal detection (Schub 2), artefact tool-call persistence (Schub 3), and the `usage` persistence fix (Schub 4.1 piggyback) as one coordinated change against both backend and frontend.

**Architecture:** Purely additive changes to shared contracts, backend adapter/inference/orchestrator/repository, and frontend types/store/UI. No Mongo migration, no new topics, no WebSocket reconnect changes. Refusals flow through the existing `ChatStreamErrorEvent` channel with `error_code="refusal"` and `recoverable=True`; artefacts get a new `artefact_refs` field on `ChatMessageDto` populated via an extended `ChatToolCallCompletedEvent` that carries an optional `artefact_ref`.

**Tech Stack:** Python 3.12 + FastAPI + Pydantic v2 (backend), React + TypeScript + Vitest (frontend), pytest (backend tests), MongoDB (storage).

**Spec:** `docs/superpowers/specs/2026-04-11-refusal-detection-and-artefact-persistence-design.md`
**Manual test plan:** `MANUAL-TESTS-REFUSAL-AND-ARTEFACTS.md` (used in Task 17)

---

## File Structure

Files this plan touches:

**Backend**
- `shared/dtos/chat.py` — new `ArtefactRefDto`, extended `ChatMessageDto` (Task 1)
- `shared/events/chat.py` — extended `ChatStreamEndedEvent.status`, extended `ChatToolCallCompletedEvent` (Task 1)
- `backend/modules/llm/_adapters/_events.py` — new `StreamRefused` event (Task 3)
- `backend/modules/llm/_adapters/_ollama_base.py` — `_is_refusal_reason` detector + `done_reason` parsing (Task 4)
- `backend/modules/chat/_inference.py` — `_REFUSAL_FALLBACK_TEXT`, refusal match arm, artefact capture, extended save_fn call (Tasks 5–7)
- `backend/modules/chat/_orchestrator.py` — extended context filter, extended save_fn closure (Task 8)
- `backend/modules/chat/_repository.py` — extended `save_message`, extended `message_to_dto` (Task 9)

**Frontend**
- `frontend/src/core/api/chat.ts` — new `ArtefactRef` type, extended `ChatMessageDto` (Task 2)
- Any TS mirror of `ChatToolCallCompletedEvent` payload — optional `artefact_ref` (Task 2)
- `frontend/src/features/chat/AssistantMessage.tsx` — `REFUSAL_FALLBACK_TEXT`, `effectiveContent`, red refused band (Task 10)
- `frontend/src/features/chat/MessageList.tsx` — persisted `ArtefactCard` render, `refusalText` prop passthrough (Task 11)
- `frontend/src/features/chat/chatStore.ts` — `streamingArtefactRefs`, `streamingRefusalText` slices (Task 12)
- `frontend/src/features/chat/useChatStream.ts` — tool-call, stream-error, stream-ended handler extensions (Tasks 13–14)

**Tests (existing files updated)**
- `tests/test_shared_chat_contracts.py` — DTO/event contract coverage (Task 1)
- `tests/test_provider_stream_events.py` — `StreamRefused` event (Task 3)
- `tests/llm/test_ollama_base.py` — `done_reason` parsing (Task 4)
- `tests/test_inference_runner.py` — inference refusal, artefact capture, save_fn guard (Tasks 5–7)
- `tests/test_chat_repository.py` — save/read roundtrip (Task 9)
- `frontend/src/features/chat/__tests__/chatStore.test.ts` — streaming state slices (Task 12)

**Tests (new files)**
- `tests/test_chat_orchestrator_filter.py` — context filter extension (Task 8) — if a test file for orchestrator filtering does not already exist under a close name
- `frontend/src/features/chat/__tests__/AssistantMessage.test.tsx` — refusal render cases (Task 10)
- `frontend/src/features/chat/__tests__/MessageList.test.tsx` — persisted artefact rendering (Task 11)
- `frontend/src/features/chat/__tests__/useChatStream.test.ts` — stream handler behaviour (Tasks 13–14)

---

## Task 1: Backend shared contracts (Python)

**Files:**
- Modify: `shared/dtos/chat.py` — add `ArtefactRefDto`, extend `ChatMessageDto`
- Modify: `shared/events/chat.py` — extend `ChatStreamEndedEvent.status`, extend `ChatToolCallCompletedEvent`, import `ArtefactRefDto`
- Test: `tests/test_shared_chat_contracts.py`

- [ ] **Step 1: Read the existing contracts to confirm current shape**

Run: `cat shared/dtos/chat.py shared/events/chat.py | head -200`

Expected: You see `ChatMessageDto`, `ChatStreamEndedEvent`, `ChatToolCallCompletedEvent`. Note existing fields and imports so your edits integrate cleanly.

- [ ] **Step 2: Write the failing contract tests**

Open `tests/test_shared_chat_contracts.py` and add at the bottom of the file (after any existing tests):

```python
# --- Refusal detection & artefact persistence contracts ---

def test_artefact_ref_dto_required_fields():
    from shared.dtos.chat import ArtefactRefDto
    ref = ArtefactRefDto(
        artefact_id="a1",
        handle="h1",
        title="My snippet",
        artefact_type="code",
        operation="create",
    )
    assert ref.artefact_id == "a1"
    assert ref.operation == "create"


def test_artefact_ref_dto_rejects_invalid_operation():
    import pytest
    from pydantic import ValidationError
    from shared.dtos.chat import ArtefactRefDto

    with pytest.raises(ValidationError):
        ArtefactRefDto(
            artefact_id="a1",
            handle="h1",
            title="t",
            artefact_type="code",
            operation="delete",  # not in Literal
        )


def test_chat_message_dto_defaults_status_to_completed():
    from shared.dtos.chat import ChatMessageDto
    from datetime import datetime, timezone
    dto = ChatMessageDto(
        id="m1",
        session_id="s1",
        role="assistant",
        content="hi",
        token_count=1,
        created_at=datetime.now(timezone.utc),
    )
    assert dto.status == "completed"
    assert dto.refusal_text is None
    assert dto.artefact_refs is None
    assert dto.usage is None


def test_chat_message_dto_accepts_refused_status_and_new_fields():
    from shared.dtos.chat import ChatMessageDto, ArtefactRefDto
    from datetime import datetime, timezone
    dto = ChatMessageDto(
        id="m1",
        session_id="s1",
        role="assistant",
        content="",
        token_count=0,
        created_at=datetime.now(timezone.utc),
        status="refused",
        refusal_text="no can do",
        artefact_refs=[
            ArtefactRefDto(
                artefact_id="a1",
                handle="h1",
                title="t",
                artefact_type="code",
                operation="create",
            )
        ],
        usage={"input_tokens": 10, "output_tokens": 5},
    )
    assert dto.status == "refused"
    assert dto.refusal_text == "no can do"
    assert dto.artefact_refs and dto.artefact_refs[0].handle == "h1"
    assert dto.usage == {"input_tokens": 10, "output_tokens": 5}


def test_chat_stream_ended_event_accepts_refused_status():
    from shared.events.chat import ChatStreamEndedEvent
    from datetime import datetime, timezone
    ev = ChatStreamEndedEvent(
        correlation_id="c1",
        session_id="s1",
        status="refused",
        context_status="green",
        timestamp=datetime.now(timezone.utc),
    )
    assert ev.status == "refused"


def test_chat_tool_call_completed_event_artefact_ref_defaults_none():
    from shared.events.chat import ChatToolCallCompletedEvent
    from datetime import datetime, timezone
    ev = ChatToolCallCompletedEvent(
        correlation_id="c1",
        tool_call_id="tc1",
        tool_name="web_search",
        success=True,
        timestamp=datetime.now(timezone.utc),
    )
    assert ev.artefact_ref is None


def test_chat_tool_call_completed_event_carries_artefact_ref():
    from shared.events.chat import ChatToolCallCompletedEvent
    from shared.dtos.chat import ArtefactRefDto
    from datetime import datetime, timezone
    ref = ArtefactRefDto(
        artefact_id="a1",
        handle="h1",
        title="t",
        artefact_type="code",
        operation="create",
    )
    ev = ChatToolCallCompletedEvent(
        correlation_id="c1",
        tool_call_id="tc1",
        tool_name="create_artefact",
        success=True,
        artefact_ref=ref,
        timestamp=datetime.now(timezone.utc),
    )
    assert ev.artefact_ref is not None
    assert ev.artefact_ref.handle == "h1"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_shared_chat_contracts.py -v -k "artefact or refused"`

Expected: All new tests fail with `AttributeError` or `ImportError` because `ArtefactRefDto` does not exist yet, `ChatMessageDto` has no `refusal_text`/`artefact_refs`/`usage` fields, and the status literal does not include `"refused"`.

- [ ] **Step 4: Add `ArtefactRefDto` and extend `ChatMessageDto` in `shared/dtos/chat.py`**

Add `ArtefactRefDto` near the top of the file (after any existing small DTOs and before `ChatMessageDto`):

```python
class ArtefactRefDto(BaseModel):
    artefact_id: str
    handle: str
    title: str
    artefact_type: str
    operation: Literal["create", "update"]
```

Then in the existing `ChatMessageDto`, change the `status` field's literal and add the three new optional fields at the end of the class (after any existing `created_at` line):

```python
    status: Literal["completed", "aborted", "refused"] = "completed"
    refusal_text: str | None = None
    artefact_refs: list[ArtefactRefDto] | None = None
    usage: dict | None = None
```

Leave every other existing field untouched.

- [ ] **Step 5: Extend events in `shared/events/chat.py`**

Add the import at the top of the file, near the other `shared.dtos.chat` imports (or add a new import line if none exists):

```python
from shared.dtos.chat import ArtefactRefDto
```

In `ChatStreamEndedEvent`, change the `status` literal from its current form to:

```python
    status: Literal["completed", "cancelled", "error", "aborted", "refused"]
```

In `ChatToolCallCompletedEvent`, add the new optional field before the trailing `timestamp` field:

```python
    artefact_ref: ArtefactRefDto | None = None
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_shared_chat_contracts.py -v -k "artefact or refused"`

Expected: All the new tests pass.

- [ ] **Step 7: Py-compile check changed files**

Run: `uv run python -m py_compile shared/dtos/chat.py shared/events/chat.py`

Expected: No output, exit code 0.

- [ ] **Step 8: Commit**

```bash
git add shared/dtos/chat.py shared/events/chat.py tests/test_shared_chat_contracts.py
git commit -m "$(cat <<'EOF'
Add ArtefactRefDto and extend ChatMessageDto, events for refusal/artefact persistence

Adds the shared contract surface for Schub 2 (refusal detection) and
Schub 3 (artefact tool call persistence): a new ArtefactRefDto, new
optional fields on ChatMessageDto (refusal_text, artefact_refs, usage),
the fifth status literal "refused" on ChatStreamEndedEvent, and an
optional artefact_ref on ChatToolCallCompletedEvent.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Frontend shared types (TypeScript)

**Files:**
- Modify: `frontend/src/core/api/chat.ts` — add `ArtefactRef`, extend `ChatMessageDto`
- Search: `frontend/src/core/events/` (and nearby) for any TS mirror of `ChatToolCallCompletedEvent` payload

- [ ] **Step 1: Read the existing interface**

Run: `cat frontend/src/core/api/chat.ts`

Expected: You see the `ChatMessageDto` interface around lines 33–46 plus any supporting types.

- [ ] **Step 2: Extend `chat.ts` with `ArtefactRef` and the new `ChatMessageDto` fields**

At a sensible location in `frontend/src/core/api/chat.ts` (next to other DTO interfaces), add:

```typescript
export interface ArtefactRef {
  artefact_id: string
  handle: string
  title: string
  artefact_type: string
  operation: 'create' | 'update'
}
```

Then extend the existing `ChatMessageDto` interface. Change the existing `status?:` field (if present) to include `'refused'`, and add three new optional properties:

```typescript
  status?: 'completed' | 'aborted' | 'refused'
  refusal_text?: string | null
  artefact_refs?: ArtefactRef[] | null
  usage?: { input_tokens?: number; output_tokens?: number } | null
```

Do not remove or rename any existing fields.

- [ ] **Step 3: Search for and update any ChatToolCallCompletedEvent TS mirror**

Run: `rg -l "chat.tool_call.completed|ChatToolCallCompleted" frontend/src --type ts --type tsx`

Expected: A short list of files (probably one or two). Open each and, where a payload interface for `chat.tool_call.completed` is declared, add the new optional field:

```typescript
  artefact_ref?: ArtefactRef | null
```

Import `ArtefactRef` from `frontend/src/core/api/chat.ts` at the top of any file that needs it. If no TypeScript payload interface exists anywhere (all event handlers cast `event.payload as Record<string, unknown>`), skip this step and leave a comment noting there is no TS mirror to update.

- [ ] **Step 4: Type-check the frontend**

Run: `cd frontend && pnpm tsc --noEmit`

Expected: No type errors. If errors appear anywhere else because a consumer destructured `ChatMessageDto` fields with older assumptions, fix them minimally — only add type narrowing, do not refactor unrelated code.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/core/api/chat.ts $(git diff --name-only frontend/src | tr '\n' ' ')
git commit -m "$(cat <<'EOF'
Extend frontend ChatMessageDto with refusal and artefact fields

Mirrors the shared Python contracts: new ArtefactRef type, new
optional fields on ChatMessageDto (refusal_text, artefact_refs,
usage), extended status literal with 'refused'. Propagates the
optional artefact_ref field into any ChatToolCallCompletedEvent
TypeScript payload mirror that was present.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `StreamRefused` adapter event

**Files:**
- Modify: `backend/modules/llm/_adapters/_events.py`
- Test: `tests/test_provider_stream_events.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_provider_stream_events.py`:

```python
def test_stream_refused_event_fields():
    from backend.modules.llm._adapters._events import StreamRefused
    ev = StreamRefused(reason="content_filter")
    assert ev.reason == "content_filter"
    assert ev.refusal_text is None

    ev2 = StreamRefused(reason="refusal", refusal_text="no can do")
    assert ev2.refusal_text == "no can do"


def test_stream_refused_is_member_of_provider_stream_event_union():
    from backend.modules.llm._adapters._events import (
        ProviderStreamEvent,
        StreamRefused,
    )
    import typing
    args = typing.get_args(ProviderStreamEvent)
    assert StreamRefused in args
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_provider_stream_events.py -v -k "refused"`

Expected: FAIL with `ImportError` — `StreamRefused` does not exist.

- [ ] **Step 3: Add `StreamRefused` to `_events.py`**

Open `backend/modules/llm/_adapters/_events.py` and add the new class beside `StreamAborted`:

```python
class StreamRefused(BaseModel):
    """Provider explicitly signalled a refusal. Terminal event on this stream.

    Either the provider emitted a known refusal marker in done_reason
    (e.g. content_filter), or a dedicated refusal field was present in
    the final chunk. Refusals are distinct from errors: the stream
    itself was healthy, the model simply declined.
    """
    reason: str
    refusal_text: str | None = None
```

Then add `StreamRefused` to the `ProviderStreamEvent` union:

```python
ProviderStreamEvent = (
    ContentDelta
    | ThinkingDelta
    | ToolCallEvent
    | StreamDone
    | StreamError
    | StreamSlow
    | StreamAborted
    | StreamRefused
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_provider_stream_events.py -v -k "refused"`

Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_events.py tests/test_provider_stream_events.py
git commit -m "$(cat <<'EOF'
Add StreamRefused adapter event for explicit provider refusals

Provides a first-class Pydantic event alongside StreamAborted so the
inference layer can match on refusal as a distinct case, rather than
shoehorning it through StreamError. reason carries the raw done_reason
value from the upstream provider, refusal_text carries an optional
structured body.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Ollama `done_reason` parsing

**Files:**
- Modify: `backend/modules/llm/_adapters/_ollama_base.py`
- Test: `tests/llm/test_ollama_base.py`

- [ ] **Step 1: Read the existing adapter to locate the final-chunk branch**

Run: `grep -n "chunk.get(\"done\")" backend/modules/llm/_adapters/_ollama_base.py`

Expected: A line number (roughly around 240) where the `if chunk.get("done"):` branch lives. Read 30 lines of surrounding context so your edit plugs in cleanly.

- [ ] **Step 2: Write the failing tests for the detector**

Add to `tests/llm/test_ollama_base.py`:

```python
def test_is_refusal_reason_known_values():
    from backend.modules.llm._adapters._ollama_base import _is_refusal_reason
    assert _is_refusal_reason("content_filter") is True
    assert _is_refusal_reason("refusal") is True


def test_is_refusal_reason_is_case_insensitive():
    from backend.modules.llm._adapters._ollama_base import _is_refusal_reason
    assert _is_refusal_reason("Content_Filter") is True
    assert _is_refusal_reason("REFUSAL") is True


def test_is_refusal_reason_normal_termination():
    from backend.modules.llm._adapters._ollama_base import _is_refusal_reason
    assert _is_refusal_reason("stop") is False
    assert _is_refusal_reason("length") is False


def test_is_refusal_reason_empty_or_none():
    from backend.modules.llm._adapters._ollama_base import _is_refusal_reason
    assert _is_refusal_reason(None) is False
    assert _is_refusal_reason("") is False
```

- [ ] **Step 3: Write the failing tests for the stream parsing**

Still in `tests/llm/test_ollama_base.py`, locate how existing tests feed a synthetic NDJSON stream through the adapter (look for fixtures that return a fake `httpx` response or something similar). Use that same mechanism to add:

```python
import json
import pytest


def _chunks_to_ndjson(chunks: list[dict]) -> list[str]:
    return [json.dumps(c) for c in chunks]


@pytest.mark.asyncio
async def test_ollama_normal_completion_emits_stream_done(monkeypatch):
    """done_reason='stop' should yield StreamDone and no log line."""
    from backend.modules.llm._adapters._events import StreamDone, StreamRefused
    # Use whatever pattern existing tests use to run stream_completion
    # with the following NDJSON sequence:
    ndjson = _chunks_to_ndjson([
        {"message": {"content": "hello"}, "done": False},
        {"done": True, "done_reason": "stop",
         "prompt_eval_count": 5, "eval_count": 2},
    ])
    events = await _collect_events_from_ndjson(ndjson)
    assert any(isinstance(e, StreamDone) for e in events)
    assert not any(isinstance(e, StreamRefused) for e in events)


@pytest.mark.asyncio
async def test_ollama_content_filter_yields_stream_refused():
    from backend.modules.llm._adapters._events import StreamDone, StreamRefused
    ndjson = _chunks_to_ndjson([
        {"message": {"content": "I decline"}, "done": False},
        {"done": True, "done_reason": "content_filter", "message": {}},
    ])
    events = await _collect_events_from_ndjson(ndjson)
    refused = [e for e in events if isinstance(e, StreamRefused)]
    assert len(refused) == 1
    assert refused[0].reason == "content_filter"
    assert refused[0].refusal_text is None
    # Must not also emit StreamDone
    assert not any(isinstance(e, StreamDone) for e in events)


@pytest.mark.asyncio
async def test_ollama_refusal_with_body():
    from backend.modules.llm._adapters._events import StreamRefused
    ndjson = _chunks_to_ndjson([
        {"done": True, "done_reason": "refusal",
         "message": {"refusal": "I can't help with that"}},
    ])
    events = await _collect_events_from_ndjson(ndjson)
    refused = [e for e in events if isinstance(e, StreamRefused)]
    assert len(refused) == 1
    assert refused[0].refusal_text == "I can't help with that"


@pytest.mark.asyncio
async def test_ollama_unknown_done_reason_emits_done_and_logs(caplog):
    from backend.modules.llm._adapters._events import StreamDone, StreamRefused
    ndjson = _chunks_to_ndjson([
        {"done": True, "done_reason": "something_new"},
    ])
    with caplog.at_level("INFO"):
        events = await _collect_events_from_ndjson(ndjson)
    assert any(isinstance(e, StreamDone) for e in events)
    assert not any(isinstance(e, StreamRefused) for e in events)
    assert any("ollama_base.done_reason" in m and "something_new" in m
               for m in caplog.messages)


@pytest.mark.asyncio
async def test_ollama_vanilla_done_reasons_do_not_log(caplog):
    ndjson = _chunks_to_ndjson([
        {"done": True, "done_reason": "stop"},
    ])
    with caplog.at_level("INFO"):
        await _collect_events_from_ndjson(ndjson)
    assert not any("ollama_base.done_reason" in m for m in caplog.messages)
```

If `_collect_events_from_ndjson` does not already exist as a helper in the test file, add it near the top based on whatever pattern existing `tests/llm/test_ollama_base.py` already uses to stream-parse NDJSON (check existing tests for `stream_completion` and copy the scaffolding). Do not invent a new mechanism — reuse what's there.

- [ ] **Step 4: Run the tests to verify they fail**

Run: `uv run pytest tests/llm/test_ollama_base.py -v -k "refusal or refused or done_reason"`

Expected: ImportError on `_is_refusal_reason` and failures on the refusal parsing tests.

- [ ] **Step 5: Add `_is_refusal_reason` and the frozenset**

At the top of `backend/modules/llm/_adapters/_ollama_base.py`, after the imports and before the class definition, add:

```python
_REFUSAL_REASONS: frozenset[str] = frozenset({"content_filter", "refusal"})


def _is_refusal_reason(reason: str | None) -> bool:
    """Return True if the Ollama done_reason value marks a refusal.

    Case-insensitive. Extension point: when new upstream providers are
    observed in production logs emitting other refusal markers, add
    them to _REFUSAL_REASONS.
    """
    if not reason:
        return False
    return reason.lower() in _REFUSAL_REASONS
```

- [ ] **Step 6: Modify the `if chunk.get("done"):` branch in `stream_completion`**

Find the current block:

```python
if chunk.get("done"):
    seen_done = True
    yield StreamDone(
        input_tokens=chunk.get("prompt_eval_count"),
        output_tokens=chunk.get("eval_count"),
    )
    break
```

Replace it with:

```python
if chunk.get("done"):
    seen_done = True
    done_reason = chunk.get("done_reason")

    # Observability: surface any non-vanilla done_reason value so we
    # can discover new refusal markers from production logs.
    if done_reason and done_reason not in ("stop", "length"):
        _log.info(
            "ollama_base.done_reason model=%s reason=%s",
            payload.get("model"), done_reason,
        )

    if _is_refusal_reason(done_reason):
        msg = chunk.get("message", {})
        refusal_body = msg.get("refusal") or None
        yield StreamRefused(
            reason=done_reason,
            refusal_text=refusal_body,
        )
        return  # Refusal is terminal; no StreamDone after this.

    yield StreamDone(
        input_tokens=chunk.get("prompt_eval_count"),
        output_tokens=chunk.get("eval_count"),
    )
    break
```

Also update the import line in the same file to include `StreamRefused`:

```python
from ._events import (
    ContentDelta,
    ThinkingDelta,
    ToolCallEvent,
    StreamDone,
    StreamError,
    StreamSlow,
    StreamAborted,
    StreamRefused,  # new
)
```

(Adapt to the existing import style — single line or multiline, whichever it uses.)

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/llm/test_ollama_base.py -v`

Expected: All tests pass (the new refusal tests plus any existing adapter tests that should still work).

- [ ] **Step 8: Py-compile check**

Run: `uv run python -m py_compile backend/modules/llm/_adapters/_ollama_base.py backend/modules/llm/_adapters/_events.py`

Expected: No output.

- [ ] **Step 9: Commit**

```bash
git add backend/modules/llm/_adapters/_ollama_base.py tests/llm/test_ollama_base.py
git commit -m "$(cat <<'EOF'
Detect refusals via Ollama done_reason and emit StreamRefused

Adds _is_refusal_reason() and the observability log for non-vanilla
done_reason values. The final-chunk branch in stream_completion now
yields StreamRefused on known refusal markers (content_filter,
refusal) and returns early without emitting StreamDone. Unknown
done_reason values are logged at info level so we can discover new
markers from production logs.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Inference — `_REFUSAL_FALLBACK_TEXT` and `StreamRefused` match arm

**Files:**
- Modify: `backend/modules/chat/_inference.py`
- Test: `tests/test_inference_runner.py`

- [ ] **Step 1: Read the existing match block over `ProviderStreamEvent`**

Run: `grep -n "case StreamAborted" backend/modules/chat/_inference.py`

Expected: A line number. Read 50 lines of surrounding context so you know exactly where the new `case StreamRefused()` arm should sit and what local variables are in scope.

- [ ] **Step 2: Write the failing test**

Add to `tests/test_inference_runner.py`. If the file has fixtures for feeding a fake stream iterator into `run_inference` and collecting emitted events + `save_fn` kwargs, reuse them. If not, add the minimal scaffolding based on existing tests in the file.

```python
@pytest.mark.asyncio
async def test_run_inference_handles_stream_refused(caplog):
    """StreamRefused → status='refused', error event with error_code='refusal',
    save_fn called with refusal fields."""
    from backend.modules.llm._adapters._events import (
        ContentDelta, StreamRefused,
    )
    from shared.events.chat import ChatStreamErrorEvent

    async def fake_stream():
        yield ContentDelta(delta="I am sorry")
        yield StreamRefused(reason="content_filter", refusal_text=None)

    emitted: list = []
    save_calls: list = []

    async def fake_emit(event):
        emitted.append(event)

    async def fake_save(**kwargs):
        save_calls.append(kwargs)
        return "msg-1"

    # Call the existing inference runner with the fixtures above. Use the
    # same calling convention as neighbouring tests in this file. The
    # model/tool/executor dependencies can be None/stub.
    with caplog.at_level("WARNING"):
        await _run_inference_with_fake_stream(
            stream=fake_stream(),
            emit_fn=fake_emit,
            save_fn=fake_save,
        )

    # Error event with refusal code emitted
    err_events = [e for e in emitted if isinstance(e, ChatStreamErrorEvent)]
    assert any(e.error_code == "refusal" and e.recoverable is True
               for e in err_events)
    # Warning log line
    assert any("chat.stream.refused" in m for m in caplog.messages)
    # save_fn called with status='refused' and refusal_text=None
    assert len(save_calls) == 1
    assert save_calls[0]["status"] == "refused"
    assert save_calls[0]["refusal_text"] is None
    assert save_calls[0]["content"] == "I am sorry"


@pytest.mark.asyncio
async def test_run_inference_refused_with_provider_body():
    from backend.modules.llm._adapters._events import StreamRefused

    async def fake_stream():
        yield StreamRefused(reason="refusal", refusal_text="I cannot help")

    emitted: list = []
    save_calls: list = []

    async def fake_emit(event):
        emitted.append(event)

    async def fake_save(**kwargs):
        save_calls.append(kwargs)
        return "msg-1"

    await _run_inference_with_fake_stream(
        stream=fake_stream(),
        emit_fn=fake_emit,
        save_fn=fake_save,
    )
    assert len(save_calls) == 1
    assert save_calls[0]["refusal_text"] == "I cannot help"
    assert save_calls[0]["status"] == "refused"
```

If `_run_inference_with_fake_stream` is not already present in the file (or a close equivalent), add it near the top of the file as a helper that calls `run_inference` with whatever signature the real function expects, supplying stub values for anything the fake stream does not exercise (cancel_event, tool_executor_fn, etc.). Copy the pattern from any existing test in the same file that exercises `run_inference` directly.

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_inference_runner.py -v -k "refused"`

Expected: FAIL with `AttributeError` or assertion errors — the new match arm does not exist yet.

- [ ] **Step 4: Add the fallback constant and match arm to `_inference.py`**

At the top of `backend/modules/chat/_inference.py`, after the imports and before any function or class definition, add:

```python
_REFUSAL_FALLBACK_TEXT = "The model declined this request."
```

Update the import of adapter events near the top of the file to include `StreamRefused`:

```python
from backend.modules.llm._adapters._events import (
    ContentDelta,
    ThinkingDelta,
    ToolCallEvent,
    StreamDone,
    StreamError,
    StreamSlow,
    StreamAborted,
    StreamRefused,  # new
)
```

In the per-iteration block where `iter_content` and `iter_thinking` are initialised, also initialise `iter_refusal_text`:

```python
iter_content = ""
iter_thinking = ""
iter_refusal_text: str | None = None  # new
```

In the match block over `ProviderStreamEvent`, add a new arm **after** the `case StreamAborted()` arm:

```python
case StreamRefused() as refused:
    _log.warning(
        "chat.stream.refused session=%s correlation_id=%s reason=%s",
        session_id, correlation_id, refused.reason,
    )
    status = "refused"
    iter_refusal_text = refused.refusal_text
    await emit_fn(ChatStreamErrorEvent(
        correlation_id=correlation_id,
        error_code="refusal",
        recoverable=True,
        user_message=refused.refusal_text or _REFUSAL_FALLBACK_TEXT,
        timestamp=datetime.now(timezone.utc),
    ))
```

- [ ] **Step 5: Extend the `save_fn` call site to forward `refusal_text` and update the guard**

Find the current `if full_content:` block around line 304:

```python
if full_content:
    message_id = await save_fn(
        content=full_content,
        thinking=full_thinking or None,
        usage=usage,
        web_search_context=web_search_context or None,
        knowledge_context=knowledge_context or None,
        status="aborted" if status == "aborted" else "completed",
    )
```

Replace it with a version that persists content-less refusals and passes `refusal_text`. **Note:** this step only adds `refusal_text` and the refused-status branch; `artefact_refs` is added in Task 6. The block becomes:

```python
if full_content or status == "refused":
    resolved_status: Literal["completed", "aborted", "refused"] = (
        "refused" if status == "refused"
        else "aborted" if status == "aborted"
        else "completed"
    )
    message_id = await save_fn(
        content=full_content,
        thinking=full_thinking or None,
        usage=usage,
        web_search_context=web_search_context or None,
        knowledge_context=knowledge_context or None,
        refusal_text=iter_refusal_text,
        status=resolved_status,
    )
```

Make sure `Literal` is imported at the top of the file (it already should be; if not, add `from typing import Literal`).

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_inference_runner.py -v -k "refused"`

Expected: Both new tests pass. This step also exercises the `save_fn` signature — the fake save function accepts `**kwargs`, so the new keyword is absorbed cleanly even before Task 8 updates the real orchestrator closure.

- [ ] **Step 7: Run the rest of the inference suite to catch regressions**

Run: `uv run pytest tests/test_inference_runner.py -v`

Expected: All tests pass. If any existing test fails because it asserted the exact set of save_fn kwargs and now sees an extra `refusal_text` kwarg, update that test to ignore or explicitly handle the new field — do not remove it.

- [ ] **Step 8: Commit**

```bash
git add backend/modules/chat/_inference.py tests/test_inference_runner.py
git commit -m "$(cat <<'EOF'
Handle StreamRefused in run_inference with fallback and save persistence

Adds the _REFUSAL_FALLBACK_TEXT module constant, the StreamRefused
match arm that sets status='refused' and emits a ChatStreamErrorEvent
with error_code='refusal' and recoverable=True, and extends the
save_fn call so content-less refusals are still persisted via the
new 'or status == refused' guard. refusal_text flows through to the
repository layer.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Inference — artefact capture in the tool loop

**Files:**
- Modify: `backend/modules/chat/_inference.py`
- Test: `tests/test_inference_runner.py`

- [ ] **Step 1: Read the existing tool-loop block**

Run: `grep -n "ChatToolCallCompletedEvent" backend/modules/chat/_inference.py`

Expected: The line numbers of the existing emission. Read 60 lines of surrounding context including the web_search and knowledge_search capture blocks that follow.

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_inference_runner.py`:

```python
@pytest.mark.asyncio
async def test_run_inference_captures_create_artefact_ref():
    """A successful create_artefact tool call → artefact_refs appended,
    ChatToolCallCompletedEvent carries the ref."""
    from backend.modules.llm._adapters._events import ToolCallEvent, StreamDone
    from shared.events.chat import ChatToolCallCompletedEvent
    from shared.dtos.chat import ArtefactRefDto
    import json

    async def fake_stream():
        yield ToolCallEvent(
            id="tc1",
            name="create_artefact",
            arguments=json.dumps({
                "handle": "h1",
                "title": "Hello snippet",
                "type": "code",
            }),
        )
        yield StreamDone(input_tokens=1, output_tokens=1)

    async def fake_tool_executor(user_id, tool_name, args_json):
        return json.dumps({"ok": True, "artefact_id": "a1", "handle": "h1"})

    emitted: list = []
    save_calls: list = []

    async def fake_emit(event):
        emitted.append(event)

    async def fake_save(**kwargs):
        save_calls.append(kwargs)
        return "msg-1"

    await _run_inference_with_fake_stream(
        stream=fake_stream(),
        emit_fn=fake_emit,
        save_fn=fake_save,
        tool_executor_fn=fake_tool_executor,
    )

    # artefact_refs passed to save_fn
    assert len(save_calls) == 1
    refs = save_calls[0].get("artefact_refs")
    assert refs == [{
        "artefact_id": "a1",
        "handle": "h1",
        "title": "Hello snippet",
        "artefact_type": "code",
        "operation": "create",
    }]

    # ChatToolCallCompletedEvent carries the ref
    completed = [e for e in emitted if isinstance(e, ChatToolCallCompletedEvent)]
    assert len(completed) == 1
    assert completed[0].artefact_ref is not None
    assert completed[0].artefact_ref.operation == "create"
    assert completed[0].artefact_ref.artefact_id == "a1"


@pytest.mark.asyncio
async def test_run_inference_captures_update_artefact_without_artefact_id():
    """update_artefact results have no artefact_id field; should end up as ''."""
    from backend.modules.llm._adapters._events import ToolCallEvent, StreamDone
    import json

    async def fake_stream():
        yield ToolCallEvent(
            id="tc2",
            name="update_artefact",
            arguments=json.dumps({"handle": "h2", "title": "x"}),
        )
        yield StreamDone()

    async def fake_tool_executor(user_id, tool_name, args_json):
        return json.dumps({"ok": True, "handle": "h2", "version": 3})

    save_calls: list = []

    async def fake_save(**kwargs):
        save_calls.append(kwargs)
        return "msg-1"

    await _run_inference_with_fake_stream(
        stream=fake_stream(),
        emit_fn=lambda e: None,
        save_fn=fake_save,
        tool_executor_fn=fake_tool_executor,
    )

    refs = save_calls[0]["artefact_refs"]
    assert len(refs) == 1
    assert refs[0]["artefact_id"] == ""
    assert refs[0]["handle"] == "h2"
    assert refs[0]["operation"] == "update"


@pytest.mark.asyncio
async def test_run_inference_skips_failed_artefact_tool_call():
    from backend.modules.llm._adapters._events import ToolCallEvent, StreamDone
    import json

    async def fake_stream():
        yield ToolCallEvent(
            id="tc3",
            name="create_artefact",
            arguments=json.dumps({"handle": "h3", "title": "x", "type": "code"}),
        )
        yield StreamDone()

    async def fake_tool_executor(user_id, tool_name, args_json):
        return json.dumps({"error": "validation failed"})

    save_calls: list = []

    async def fake_save(**kwargs):
        save_calls.append(kwargs)
        return "msg-1"

    await _run_inference_with_fake_stream(
        stream=fake_stream(),
        emit_fn=lambda e: None,
        save_fn=fake_save,
        tool_executor_fn=fake_tool_executor,
    )

    # No artefact_refs captured for a failed tool call
    assert save_calls[0].get("artefact_refs") is None


@pytest.mark.asyncio
async def test_run_inference_preserves_artefact_call_order():
    """create + update in the same turn → [create, update] ordering."""
    from backend.modules.llm._adapters._events import ToolCallEvent, StreamDone
    import json

    async def fake_stream():
        yield ToolCallEvent(
            id="tc4",
            name="create_artefact",
            arguments=json.dumps({"handle": "h", "title": "t1", "type": "code"}),
        )
        yield ToolCallEvent(
            id="tc5",
            name="update_artefact",
            arguments=json.dumps({"handle": "h", "title": "t2"}),
        )
        yield StreamDone()

    async def fake_tool_executor(user_id, tool_name, args_json):
        if tool_name == "create_artefact":
            return json.dumps({"ok": True, "artefact_id": "a", "handle": "h"})
        return json.dumps({"ok": True, "handle": "h", "version": 2})

    save_calls: list = []

    async def fake_save(**kwargs):
        save_calls.append(kwargs)
        return "msg-1"

    await _run_inference_with_fake_stream(
        stream=fake_stream(),
        emit_fn=lambda e: None,
        save_fn=fake_save,
        tool_executor_fn=fake_tool_executor,
    )

    refs = save_calls[0]["artefact_refs"]
    assert [r["operation"] for r in refs] == ["create", "update"]
    assert refs[0]["title"] == "t1"
    assert refs[1]["title"] == "t2"
```

Reuse the `_run_inference_with_fake_stream` helper from Task 5, extending it to accept an optional `tool_executor_fn` kwarg if it does not already.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_inference_runner.py -v -k "artefact"`

Expected: FAIL — `artefact_refs` is not in `save_fn` kwargs, `ChatToolCallCompletedEvent.artefact_ref` is not attached.

- [ ] **Step 4: Initialise `artefact_refs` at the top of the inference loop**

In `backend/modules/chat/_inference.py`, at the same place where `web_search_context` and `knowledge_context` are initialised as empty lists, add:

```python
artefact_refs: list[dict] = []
```

- [ ] **Step 5: Restructure the `ChatToolCallCompletedEvent` emission**

Find the existing tool-loop block. The current shape is roughly:

```python
await emit_fn(ChatToolCallStartedEvent(...))
result_str = await tool_executor_fn(user_id, tc.name, tc.arguments)
try:
    parsed_result = json.loads(result_str)
    tool_success = not (isinstance(parsed_result, dict) and "error" in parsed_result)
except (json.JSONDecodeError, TypeError):
    tool_success = True

await emit_fn(ChatToolCallCompletedEvent(
    correlation_id=correlation_id,
    tool_call_id=tc.id,
    tool_name=tc.name,
    success=tool_success,
    timestamp=datetime.now(timezone.utc),
))

# ... existing web_search / knowledge_search capture blocks follow ...
```

Insert the artefact capture **between** the `tool_success` block and the `ChatToolCallCompletedEvent` emission, then attach the computed ref to the emission. Do **not** move the web_search/knowledge_search blocks — they stay where they are.

```python
# Capture artefact tool calls BEFORE emitting the completed event so
# the ref can be attached to the event payload.
ref_for_event: ArtefactRefDto | None = None
if tc.name in ("create_artefact", "update_artefact"):
    try:
        parsed = json.loads(result_str)
        if isinstance(parsed, dict) and parsed.get("ok"):
            ref_dict = {
                "artefact_id": parsed.get("artefact_id", ""),
                "handle": parsed.get("handle") or arguments.get("handle", ""),
                "title": arguments.get("title", ""),
                "artefact_type": arguments.get("type", ""),
                "operation": (
                    "create" if tc.name == "create_artefact" else "update"
                ),
            }
            artefact_refs.append(ref_dict)
            ref_for_event = ArtefactRefDto(**ref_dict)
    except (json.JSONDecodeError, TypeError):
        pass

await emit_fn(ChatToolCallCompletedEvent(
    correlation_id=correlation_id,
    tool_call_id=tc.id,
    tool_name=tc.name,
    success=tool_success,
    artefact_ref=ref_for_event,
    timestamp=datetime.now(timezone.utc),
))
```

**Note on `arguments`**: the existing code should already `arguments = json.loads(tc.arguments)` near the start of the tool-loop iteration (you saw it in Step 1). If not, parse it there so `arguments.get("handle")` works. Do not re-parse.

Add the import at the top of `_inference.py`:

```python
from shared.dtos.chat import ArtefactRefDto
```

- [ ] **Step 6: Extend the `save_fn` call to pass `artefact_refs`**

Find the `save_fn` call from Task 5 and add the `artefact_refs` kwarg:

```python
if full_content or status == "refused":
    resolved_status: Literal["completed", "aborted", "refused"] = (
        "refused" if status == "refused"
        else "aborted" if status == "aborted"
        else "completed"
    )
    message_id = await save_fn(
        content=full_content,
        thinking=full_thinking or None,
        usage=usage,
        web_search_context=web_search_context or None,
        knowledge_context=knowledge_context or None,
        artefact_refs=artefact_refs or None,
        refusal_text=iter_refusal_text,
        status=resolved_status,
    )
```

- [ ] **Step 7: Run the artefact tests to verify they pass**

Run: `uv run pytest tests/test_inference_runner.py -v -k "artefact"`

Expected: All four new tests pass.

- [ ] **Step 8: Run the full inference suite**

Run: `uv run pytest tests/test_inference_runner.py -v`

Expected: All pass. If any pre-existing test fails because it asserts exact save_fn kwargs and `artefact_refs=None` is an unexpected extra, update that assertion to allow the new kwarg.

- [ ] **Step 9: Commit**

```bash
git add backend/modules/chat/_inference.py tests/test_inference_runner.py
git commit -m "$(cat <<'EOF'
Capture create/update artefact tool calls as refs in chat inference

Adds a new artefact_refs list to the per-turn inference loop. Each
successful create_artefact or update_artefact tool call appends a
dict with artefact_id, handle, title, artefact_type, operation. The
ChatToolCallCompletedEvent now carries a matching ArtefactRefDto so
the frontend can pick up the ref without polling tool results. The
save_fn call forwards artefact_refs to the repository.

Append order is preserved, failed tool calls are skipped, and
update_artefact calls (which have no artefact_id in the result)
store an empty string for that field.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Orchestrator — context filter and save_fn closure

**Files:**
- Modify: `backend/modules/chat/_orchestrator.py`
- Test: `tests/test_inference_runner.py` (if the orchestrator has its own test file, also extend that — check via `grep -l "_orchestrator" tests/`)

- [ ] **Step 1: Read the existing context filter and save_fn closure**

Run: `grep -n "status.*aborted\|async def save_fn\|save_message" backend/modules/chat/_orchestrator.py | head -30`

Expected: Line numbers for the filter (around 311) and the closure (around 485). Read the surrounding code.

- [ ] **Step 2: Write the failing test for the context filter**

Locate or create a test that exercises the history-filtering behaviour of the orchestrator. If there is no dedicated orchestrator test file, add a simple unit test in `tests/test_inference_runner.py` that imports and calls the filter logic directly, or extracts it into a testable helper.

The easiest path: the filter is a list comprehension inline in `_orchestrator.py`. Refactor it to call a tiny pure helper and test the helper:

```python
def test_history_filter_excludes_aborted_and_refused():
    from backend.modules.chat._orchestrator import _filter_usable_history
    docs = [
        {"_id": "1", "status": "completed"},
        {"_id": "2", "status": "aborted"},
        {"_id": "3", "status": "refused"},
        {"_id": "4"},  # legacy, no status
    ]
    result = _filter_usable_history(docs)
    assert [d["_id"] for d in result] == ["1", "4"]
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/test_inference_runner.py -v -k "history_filter"`

Expected: ImportError — `_filter_usable_history` does not exist.

- [ ] **Step 4: Refactor the context filter into a helper and extend it**

In `backend/modules/chat/_orchestrator.py`, add a module-level helper near the top (after imports):

```python
def _filter_usable_history(docs: list[dict]) -> list[dict]:
    """Exclude messages that must not enter the LLM context.

    Aborted messages are interrupted/incomplete and pollute context.
    Refused messages are known to poison context with further refusals.
    """
    return [
        d for d in docs
        if d.get("status", "completed") not in ("aborted", "refused")
    ]
```

Then replace the existing inline list comprehension (currently around lines 311–314):

```python
history_docs = [
    d for d in history_docs
    if d.get("status", "completed") != "aborted"
]
```

with:

```python
history_docs = _filter_usable_history(history_docs)
```

- [ ] **Step 5: Extend the `save_fn` closure signature**

Find the closure (around lines 485–503). Change its signature and forward the new kwargs to `repo.save_message`:

```python
async def save_fn(
    content: str,
    thinking: str | None = None,
    usage: dict | None = None,
    web_search_context: list | None = None,
    knowledge_context: list | None = None,
    artefact_refs: list | None = None,
    refusal_text: str | None = None,
    status: Literal["completed", "aborted", "refused"] = "completed",
) -> str:
    doc = await repo.save_message(
        session_id=session_id,
        role="assistant",
        content=content,
        token_count=_compute_token_count(content, thinking),
        thinking=thinking,
        usage=usage,
        web_search_context=web_search_context,
        knowledge_context=knowledge_context,
        artefact_refs=artefact_refs,
        refusal_text=refusal_text,
        status=status,
    )
    return doc["_id"]
```

Two things to be careful about:
1. **Keep `usage=usage` in the save_message call.** This is the Schub 4.1 piggyback — the value was already being accepted by the closure today but was silently dropped on its way to `save_message`. Now it flows through.
2. The existing `_compute_token_count` or whatever the closure uses to compute `token_count` stays unchanged.

- [ ] **Step 6: Run the context filter test**

Run: `uv run pytest tests/test_inference_runner.py -v -k "history_filter"`

Expected: PASS.

- [ ] **Step 7: Py-compile check**

Run: `uv run python -m py_compile backend/modules/chat/_orchestrator.py`

Expected: No output. If the `save_message` call fails to type-check at this stage because `repo.save_message` does not yet accept `artefact_refs`/`refusal_text`/`usage`, that is expected — Task 9 adds those. The py_compile check passes because Python is duck-typed; the runtime check will pass after Task 9.

- [ ] **Step 8: Commit**

```bash
git add backend/modules/chat/_orchestrator.py tests/test_inference_runner.py
git commit -m "$(cat <<'EOF'
Extend context filter for refused messages and forward new save kwargs

Refactors the inline aborted-only history filter into a named helper
_filter_usable_history that also excludes refused messages (poison
context protection). The save_fn closure signature gains three new
kwargs (artefact_refs, refusal_text) and the new 'refused' status
literal, and finally forwards usage to save_message, closing the
Schub 4.1 drift from Schub 1.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Repository — `save_message` and `message_to_dto`

**Files:**
- Modify: `backend/modules/chat/_repository.py`
- Test: `tests/test_chat_repository.py`

- [ ] **Step 1: Read the existing `save_message` and `message_to_dto`**

Run: `grep -n "def save_message\|def message_to_dto" backend/modules/chat/_repository.py`

Expected: Line numbers. Read both functions fully.

- [ ] **Step 2: Write the failing tests**

Add to `tests/test_chat_repository.py`:

```python
@pytest.mark.asyncio
async def test_save_message_persists_new_fields_and_roundtrip(chat_repo):
    from shared.dtos.chat import ArtefactRefDto

    doc = await chat_repo.save_message(
        session_id="s1",
        role="assistant",
        content="",
        token_count=0,
        thinking=None,
        usage={"input_tokens": 10, "output_tokens": 5},
        artefact_refs=[{
            "artefact_id": "a1",
            "handle": "h1",
            "title": "Snippet",
            "artefact_type": "code",
            "operation": "create",
        }],
        refusal_text="The model declined this request.",
        status="refused",
    )
    assert doc["status"] == "refused"
    assert doc["refusal_text"] == "The model declined this request."
    assert doc["usage"] == {"input_tokens": 10, "output_tokens": 5}
    assert doc["artefact_refs"][0]["handle"] == "h1"

    # Roundtrip through message_to_dto
    dto = chat_repo.message_to_dto(doc)
    assert dto.status == "refused"
    assert dto.refusal_text == "The model declined this request."
    assert dto.usage == {"input_tokens": 10, "output_tokens": 5}
    assert dto.artefact_refs and dto.artefact_refs[0].handle == "h1"
    assert isinstance(dto.artefact_refs[0], ArtefactRefDto)


@pytest.mark.asyncio
async def test_save_message_legacy_document_reads_with_defaults(chat_repo):
    # Insert a legacy document (no status, no refusal_text, no artefact_refs, no usage)
    from datetime import datetime, timezone
    from uuid import uuid4
    doc = {
        "_id": str(uuid4()),
        "session_id": "s1",
        "role": "assistant",
        "content": "hi",
        "thinking": None,
        "token_count": 1,
        "created_at": datetime.now(timezone.utc),
    }
    dto = chat_repo.message_to_dto(doc)
    assert dto.status == "completed"
    assert dto.refusal_text is None
    assert dto.artefact_refs is None
    assert dto.usage is None


@pytest.mark.asyncio
async def test_save_message_empty_artefact_refs_not_written(chat_repo):
    doc = await chat_repo.save_message(
        session_id="s1",
        role="assistant",
        content="ok",
        token_count=1,
        artefact_refs=[],
    )
    assert "artefact_refs" not in doc
```

If there is no `chat_repo` fixture already in the file, look at how existing tests in the file instantiate the repository (it probably uses a fake Mongo collection or `mongomock`). Reuse the exact same pattern.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_chat_repository.py -v -k "new_fields or legacy_document or empty_artefact"`

Expected: FAIL — the `save_message` signature does not yet accept `usage`, `artefact_refs`, `refusal_text`, or the new status literal, and `message_to_dto` does not read them.

- [ ] **Step 4: Extend `save_message` signature in `_repository.py`**

Change the current signature to accept the new kwargs. Current form (simplified):

```python
async def save_message(
    self,
    session_id: str,
    role: str,
    content: str,
    token_count: int,
    thinking: str | None = None,
    web_search_context: list[dict] | None = None,
    knowledge_context: list[dict] | None = None,
    attachment_ids: list[str] | None = None,
    attachment_refs: list[dict] | None = None,
    vision_descriptions_used: list[dict] | None = None,
    status: Literal["completed", "aborted"] = "completed",
) -> dict:
```

Becomes:

```python
async def save_message(
    self,
    session_id: str,
    role: str,
    content: str,
    token_count: int,
    thinking: str | None = None,
    usage: dict | None = None,
    web_search_context: list[dict] | None = None,
    knowledge_context: list[dict] | None = None,
    attachment_ids: list[str] | None = None,
    attachment_refs: list[dict] | None = None,
    vision_descriptions_used: list[dict] | None = None,
    artefact_refs: list[dict] | None = None,
    refusal_text: str | None = None,
    status: Literal["completed", "aborted", "refused"] = "completed",
) -> dict:
```

Inside the function, after the existing `if vision_descriptions_used:` block and before `await self._messages.insert_one(doc)`, add the three new conditional writes:

```python
    if usage:
        doc["usage"] = usage
    if artefact_refs:
        doc["artefact_refs"] = artefact_refs
    if refusal_text:
        doc["refusal_text"] = refusal_text
```

Do not touch the existing field writes.

- [ ] **Step 5: Extend `message_to_dto` to read the new fields**

Find the current return statement at the bottom of `message_to_dto`. Before the return, add:

```python
    raw_artefact_refs = doc.get("artefact_refs")
    artefact_refs = (
        [
            ArtefactRefDto(
                artefact_id=ref.get("artefact_id", ""),
                handle=ref.get("handle", ""),
                title=ref.get("title", ""),
                artefact_type=ref.get("artefact_type", ""),
                operation=ref.get("operation", "create"),
            )
            for ref in raw_artefact_refs
        ]
        if raw_artefact_refs
        else None
    )
```

Make sure `ArtefactRefDto` is imported at the top of the file alongside `ChatMessageDto`:

```python
from shared.dtos.chat import ChatMessageDto, ArtefactRefDto  # add ArtefactRefDto
```

Extend the `return ChatMessageDto(...)` call to include the new fields:

```python
    return ChatMessageDto(
        id=doc["_id"],
        session_id=doc["session_id"],
        role=doc["role"],
        content=doc["content"],
        thinking=doc.get("thinking"),
        token_count=doc["token_count"],
        attachments=attachments,
        web_search_context=ws_ctx,
        knowledge_context=doc.get("knowledge_context"),
        vision_descriptions_used=vision_snaps,
        created_at=doc["created_at"],
        status=doc.get("status", "completed"),
        refusal_text=doc.get("refusal_text"),
        artefact_refs=artefact_refs,
        usage=doc.get("usage"),
    )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_chat_repository.py -v -k "new_fields or legacy_document or empty_artefact"`

Expected: All three new tests pass.

- [ ] **Step 7: Run the full repository suite**

Run: `uv run pytest tests/test_chat_repository.py -v`

Expected: All pass. Update any existing test that now asserts the exact set of fields present on a saved doc if it was asserting "must not have `usage`/`artefact_refs`/`refusal_text`" — those assertions were coincidentally passing before.

- [ ] **Step 8: Commit**

```bash
git add backend/modules/chat/_repository.py tests/test_chat_repository.py
git commit -m "$(cat <<'EOF'
Persist usage, artefact_refs, refusal_text on chat messages

save_message gains three new optional kwargs and accepts the
'refused' status literal. All three fields are only written to the
Mongo document when truthy, keeping legacy-compatible documents
minimal. message_to_dto reads all three with safe defaults so
pre-existing documents continue to load correctly.

This commit also closes the Schub 4.1 drift: usage is now
persisted alongside every chat message that declares one.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Backend integration smoke test

**Files:** None modified — this task only runs the existing suite.

- [ ] **Step 1: Run the full backend test suite**

Run: `uv run pytest tests/ -v`

Expected: All tests pass. If anything fails, read the failure and decide: is it a genuine regression caused by the contract changes (fix it), or is it unrelated to this work (leave it and note it)?

- [ ] **Step 2: Py-compile all changed backend files**

Run: `uv run python -m py_compile shared/dtos/chat.py shared/events/chat.py backend/modules/llm/_adapters/_events.py backend/modules/llm/_adapters/_ollama_base.py backend/modules/chat/_inference.py backend/modules/chat/_orchestrator.py backend/modules/chat/_repository.py`

Expected: No output, exit code 0.

- [ ] **Step 3: No commit needed if nothing changed**

If fixes were required to make the suite green, commit them with a message describing the fix. Otherwise, proceed to Task 10.

---

## Task 10: Frontend — `AssistantMessage` refusal rendering

**Files:**
- Modify: `frontend/src/features/chat/AssistantMessage.tsx`
- Test: `frontend/src/features/chat/__tests__/AssistantMessage.test.tsx` (create if missing)

- [ ] **Step 1: Read the existing component**

Run: `cat frontend/src/features/chat/AssistantMessage.tsx`

Expected: You see the props interface, the aborted amber band, and the main markdown render area.

- [ ] **Step 2: Write the failing tests**

Create (or extend) `frontend/src/features/chat/__tests__/AssistantMessage.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { AssistantMessage } from '../AssistantMessage'

// The component's existing tests (if any) should guide the exact props
// you pass. This block only tests the new refusal behaviour.

describe('AssistantMessage — refusal', () => {
  const baseProps = {
    thinking: null,
    isStreaming: false,
    accentColour: '#000',
    highlighter: null,
    isBookmarked: false,
    onBookmark: () => {},
    canRegenerate: false,
    onRegenerate: () => {},
  } as const

  it('renders content and red band when refused with content', () => {
    render(
      <AssistantMessage
        {...baseProps}
        content="Sorry, I will not help with that"
        status="refused"
        refusalText={null}
      />
    )
    expect(screen.getByText(/Sorry, I will not help with that/)).toBeInTheDocument()
    expect(screen.getByText(/The model declined this request/)).toBeInTheDocument()
  })

  it('renders refusalText when content is empty', () => {
    render(
      <AssistantMessage
        {...baseProps}
        content=""
        status="refused"
        refusalText="Model declined"
      />
    )
    expect(screen.getByText(/Model declined/)).toBeInTheDocument()
  })

  it('renders fallback when both content and refusalText are empty', () => {
    render(
      <AssistantMessage
        {...baseProps}
        content=""
        status="refused"
        refusalText={null}
      />
    )
    // Fallback constant matches _REFUSAL_FALLBACK_TEXT on the backend
    expect(screen.getAllByText(/The model declined this request/).length).toBeGreaterThan(0)
  })

  it('ignores refusalText when status is completed', () => {
    render(
      <AssistantMessage
        {...baseProps}
        content="Hello"
        status="completed"
        refusalText="Stray refusal"
      />
    )
    expect(screen.getByText('Hello')).toBeInTheDocument()
    expect(screen.queryByText('Stray refusal')).not.toBeInTheDocument()
  })

  it('still renders amber band when status is aborted (regression)', () => {
    render(
      <AssistantMessage
        {...baseProps}
        content="partial"
        status="aborted"
        refusalText={null}
      />
    )
    expect(screen.getByText(/interrupted/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd frontend && pnpm vitest run src/features/chat/__tests__/AssistantMessage.test.tsx`

Expected: FAIL — the component does not yet accept a `refusalText` prop, and rendering refused-with-no-content falls back to nothing.

- [ ] **Step 4: Extend `AssistantMessage.tsx`**

Add the module-level constant at the top of the file:

```tsx
const REFUSAL_FALLBACK_TEXT = 'The model declined this request.'
```

Extend the props interface:

```typescript
interface AssistantMessageProps {
  content: string
  thinking: string | null
  isStreaming: boolean
  accentColour: string
  highlighter: Highlighter | null
  isBookmarked?: boolean
  onBookmark?: () => void
  canRegenerate?: boolean
  onRegenerate?: () => void
  status?: 'completed' | 'aborted' | 'refused'
  refusalText?: string | null
}
```

Introduce the `effectiveContent` resolver at the top of the function body (before the current `return`):

```tsx
const effectiveContent = (() => {
  if (content) return content
  if (refusalText) return refusalText
  if (status === 'refused') return REFUSAL_FALLBACK_TEXT
  return ''
})()
```

Replace the current `<MarkdownRenderer content={content} ... />` usage with `<MarkdownRenderer content={effectiveContent} ... />` — the rest of the render path stays the same.

Add the new red band below the existing amber band (do not remove the amber one):

```tsx
{status === 'refused' && !isStreaming && (
  <div className="mt-2 flex items-start gap-2 rounded-md border border-red-400/40 bg-red-500/5 px-3 py-2">
    <svg
      width="14"
      height="14"
      viewBox="0 0 14 14"
      fill="none"
      className="text-red-400 mt-0.5 shrink-0"
      aria-hidden="true"
    >
      <circle cx="7" cy="7" r="6" stroke="currentColor" strokeWidth="1.2" />
      <path
        d="M4.5 4.5L9.5 9.5M9.5 4.5L4.5 9.5"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
    </svg>
    <div className="text-[11px] leading-snug text-red-200/90">
      The model declined this request. Click <strong>Regenerate</strong> to try again.
    </div>
  </div>
)}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && pnpm vitest run src/features/chat/__tests__/AssistantMessage.test.tsx`

Expected: All five tests pass.

- [ ] **Step 6: Type-check the frontend**

Run: `cd frontend && pnpm tsc --noEmit`

Expected: No errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/chat/AssistantMessage.tsx frontend/src/features/chat/__tests__/AssistantMessage.test.tsx
git commit -m "$(cat <<'EOF'
Render refusal red band and resolve refusalText fallback in AssistantMessage

Adds a new refused render state with a red crossed-circle warning
band, semantically distinct from the amber interrupted band from
Schub 1. Content resolution follows a three-level hierarchy:
actual content > provider refusal_text > REFUSAL_FALLBACK_TEXT
constant mirroring the backend _REFUSAL_FALLBACK_TEXT.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Frontend — `MessageList` persisted artefact rendering

**Files:**
- Modify: `frontend/src/features/chat/MessageList.tsx`
- Test: `frontend/src/features/chat/__tests__/MessageList.test.tsx` (create if missing)

- [ ] **Step 1: Read the existing component**

Run: `cat frontend/src/features/chat/MessageList.tsx`

Expected: You see the assistant-message branch around lines 100–138 with `WebSearchPills` and `KnowledgePills` rendered, followed by `<AssistantMessage>`.

- [ ] **Step 2: Write the failing tests**

Create `frontend/src/features/chat/__tests__/MessageList.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MessageList } from '../MessageList'
import type { ChatMessageDto } from '../../../core/api/chat'

// Mock ArtefactCard to a simple identifying div so tests only verify
// rendering contract, not the card's internals.
vi.mock('../../artefact/ArtefactCard', () => ({
  ArtefactCard: ({ handle, title, isUpdate }: any) => (
    <div data-testid="artefact-card">
      {handle}/{title}/{isUpdate ? 'update' : 'create'}
    </div>
  ),
}))

function makeMsg(overrides: Partial<ChatMessageDto>): ChatMessageDto {
  return {
    id: 'm1',
    session_id: 's1',
    role: 'assistant',
    content: 'hello',
    thinking: null,
    token_count: 0,
    attachments: null,
    web_search_context: null,
    knowledge_context: null,
    created_at: new Date().toISOString(),
    ...overrides,
  } as ChatMessageDto
}

describe('MessageList — persisted artefact rendering', () => {
  const baseProps = {
    sessionId: 's1',
    isStreaming: false,
    activeToolCalls: [],
    accentColour: '#000',
    highlighter: null,
    bookmarks: [],
    onBookmark: () => {},
    canRegenerate: false,
    onRegenerate: () => {},
  } as const

  it('renders ArtefactCard for each persisted artefact_ref', () => {
    const messages = [
      makeMsg({
        artefact_refs: [
          {
            artefact_id: 'a1',
            handle: 'h1',
            title: 't1',
            artefact_type: 'code',
            operation: 'create',
          },
        ],
      }),
    ]
    render(<MessageList {...baseProps} messages={messages} />)
    const card = screen.getByTestId('artefact-card')
    expect(card.textContent).toContain('h1/t1/create')
  })

  it('renders update operation cards distinctly', () => {
    const messages = [
      makeMsg({
        artefact_refs: [
          {
            artefact_id: '',
            handle: 'h2',
            title: 't2',
            artefact_type: 'code',
            operation: 'update',
          },
        ],
      }),
    ]
    render(<MessageList {...baseProps} messages={messages} />)
    const card = screen.getByTestId('artefact-card')
    expect(card.textContent).toContain('h2/t2/update')
  })

  it('renders multiple artefact_refs in order', () => {
    const messages = [
      makeMsg({
        artefact_refs: [
          {
            artefact_id: 'a1',
            handle: 'h',
            title: 't1',
            artefact_type: 'code',
            operation: 'create',
          },
          {
            artefact_id: '',
            handle: 'h',
            title: 't2',
            artefact_type: 'code',
            operation: 'update',
          },
        ],
      }),
    ]
    render(<MessageList {...baseProps} messages={messages} />)
    const cards = screen.getAllByTestId('artefact-card')
    expect(cards).toHaveLength(2)
    expect(cards[0].textContent).toContain('t1')
    expect(cards[1].textContent).toContain('t2')
  })

  it('renders no ArtefactCard when artefact_refs is missing', () => {
    const messages = [makeMsg({ artefact_refs: null })]
    render(<MessageList {...baseProps} messages={messages} />)
    expect(screen.queryByTestId('artefact-card')).not.toBeInTheDocument()
  })
})
```

The props on `<MessageList>` in the test should match the real component's prop shape. If it takes more or differently-named props, adjust the `baseProps` object — do not alter the component's API to fit the test.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd frontend && pnpm vitest run src/features/chat/__tests__/MessageList.test.tsx`

Expected: FAIL — the `ArtefactCard` rendering branch does not exist yet for persisted messages.

- [ ] **Step 4: Extend `MessageList.tsx`**

Locate the assistant-message render branch inside the `messages.map(...)` (currently around lines 100–138). Between the existing `{msg.knowledge_context && ... <KnowledgePills>}` line and the `<AssistantMessage ...>` element, insert:

```tsx
{msg.artefact_refs && msg.artefact_refs.length > 0 && (
  <div className="my-2 flex flex-col gap-2">
    {msg.artefact_refs.map((ref) => (
      <ArtefactCard
        key={`${msg.id}-${ref.artefact_id || ref.handle}-${ref.operation}`}
        handle={ref.handle}
        title={ref.title}
        artefactType={ref.artefact_type}
        isUpdate={ref.operation === 'update'}
        sessionId={sessionId!}
      />
    ))}
  </div>
)}
```

Also pass `refusalText` through to `<AssistantMessage>`:

```tsx
<AssistantMessage
  content={msg.content}
  thinking={msg.thinking}
  isStreaming={false}
  accentColour={accentColour}
  highlighter={highlighter}
  isBookmarked={isBm}
  onBookmark={() => onBookmark(msg.id)}
  canRegenerate={canRegenerate && i === lastAssistantIdx}
  onRegenerate={onRegenerate}
  status={msg.status ?? 'completed'}
  refusalText={msg.refusal_text ?? null}
/>
```

Import `ArtefactCard` at the top of the file if it is not already imported.

Leave the live-streaming block (the `{isStreaming && (...)}` section that renders `activeToolCalls`) unchanged.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && pnpm vitest run src/features/chat/__tests__/MessageList.test.tsx`

Expected: All four tests pass.

- [ ] **Step 6: Type-check**

Run: `cd frontend && pnpm tsc --noEmit`

Expected: No errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/chat/MessageList.tsx frontend/src/features/chat/__tests__/MessageList.test.tsx
git commit -m "$(cat <<'EOF'
Render persisted ArtefactCards from msg.artefact_refs in MessageList

Adds a new render pass between KnowledgePills and AssistantMessage
that renders one ArtefactCard per persisted artefact_ref on the
message, using handle and operation to distinguish create/update.
The live-streaming activeToolCalls render block stays unchanged —
live and persisted rendering are intentionally separate render
trees. Also passes refusalText through to AssistantMessage so
refused messages can render their fallback content.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Frontend — `chatStore` streaming slices

**Files:**
- Modify: `frontend/src/features/chat/chatStore.ts` (or equivalent — search for the file that defines `useChatStore` / `finishStreaming`)
- Test: `frontend/src/features/chat/__tests__/chatStore.test.ts`

- [ ] **Step 1: Find the store file and read it**

Run: `rg -l "finishStreaming\s*:" frontend/src`

Expected: One file. Open it, read the state shape and actions.

- [ ] **Step 2: Write the failing tests**

Extend `frontend/src/features/chat/__tests__/chatStore.test.ts`:

```typescript
import { describe, it, expect } from 'vitest'
import { useChatStore } from '../chatStore'

describe('chatStore — streaming artefact and refusal slices', () => {
  beforeEach(() => {
    // Reset the store between tests — use whatever reset helper
    // the existing tests in this file use. If they call set(initialState)
    // directly, mirror that.
    useChatStore.setState({
      streamingArtefactRefs: [],
      streamingRefusalText: null,
    } as any)
  })

  it('appendArtefactRef adds to streamingArtefactRefs', () => {
    useChatStore.getState().appendArtefactRef({
      artefact_id: 'a1',
      handle: 'h1',
      title: 't1',
      artefact_type: 'code',
      operation: 'create',
    })
    expect(useChatStore.getState().streamingArtefactRefs).toHaveLength(1)
    expect(useChatStore.getState().streamingArtefactRefs[0].handle).toBe('h1')
  })

  it('setStreamingRefusalText sets the refusal text', () => {
    useChatStore.getState().setStreamingRefusalText('declined')
    expect(useChatStore.getState().streamingRefusalText).toBe('declined')
  })

  it('finishStreaming clears the new streaming fields', () => {
    useChatStore.getState().appendArtefactRef({
      artefact_id: 'a1',
      handle: 'h1',
      title: 't1',
      artefact_type: 'code',
      operation: 'create',
    })
    useChatStore.getState().setStreamingRefusalText('declined')

    // Construct a minimal final message matching the real shape
    const finalMessage = {
      id: 'm1',
      session_id: 's1',
      role: 'assistant' as const,
      content: 'hi',
      thinking: null,
      token_count: 0,
      attachments: null,
      web_search_context: null,
      knowledge_context: null,
      created_at: new Date().toISOString(),
      status: 'completed' as const,
    }
    useChatStore.getState().finishStreaming(finalMessage, 'green', 0)
    expect(useChatStore.getState().streamingArtefactRefs).toEqual([])
    expect(useChatStore.getState().streamingRefusalText).toBeNull()
  })
})
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd frontend && pnpm vitest run src/features/chat/__tests__/chatStore.test.ts`

Expected: FAIL — `streamingArtefactRefs`, `streamingRefusalText`, `appendArtefactRef`, `setStreamingRefusalText` do not exist.

- [ ] **Step 4: Extend the store**

Open the chat store file. Add the new state fields to the state interface / initial-state literal:

```typescript
streamingArtefactRefs: ArtefactRef[]
streamingRefusalText: string | null
```

Initial values: `streamingArtefactRefs: []`, `streamingRefusalText: null`. Import `ArtefactRef` from `../../core/api/chat` at the top of the file.

Add the two new actions:

```typescript
appendArtefactRef: (ref: ArtefactRef) =>
  set((s) => ({
    streamingArtefactRefs: [...s.streamingArtefactRefs, ref],
  })),

setStreamingRefusalText: (text: string | null) =>
  set({ streamingRefusalText: text }),
```

In the existing `finishStreaming` reducer, add the two new fields to the state reset alongside the other `streaming*` cleanups:

```typescript
finishStreaming: (finalMessage, contextStatus, fillPercentage) =>
  set((s) => ({
    isWaitingForResponse: false,
    isStreaming: false,
    correlationId: null,
    streamingContent: '',
    streamingThinking: '',
    streamingWebSearchContext: [],
    streamingKnowledgeContext: [],
    streamingArtefactRefs: [],
    streamingRefusalText: null,
    activeToolCalls: [],
    streamingSlow: false,
    messages: [...s.messages, finalMessage],
    contextStatus,
    contextFillPercentage: fillPercentage,
  })),
```

Do not remove any existing fields from the reducer.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && pnpm vitest run src/features/chat/__tests__/chatStore.test.ts`

Expected: PASS.

- [ ] **Step 6: Type-check**

Run: `cd frontend && pnpm tsc --noEmit`

Expected: No errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/chat/chatStore.ts frontend/src/features/chat/__tests__/chatStore.test.ts
git commit -m "$(cat <<'EOF'
Add streamingArtefactRefs and streamingRefusalText slices to chat store

New state fields and actions for collecting artefact refs and the
refusal text during an active stream, plus the finishStreaming
reducer now resets both fields alongside existing streaming state.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Frontend — `useChatStream` tool-call and error handlers

**Files:**
- Modify: `frontend/src/features/chat/useChatStream.ts`
- Test: `frontend/src/features/chat/__tests__/useChatStream.test.ts` (create if missing)

- [ ] **Step 1: Read the existing handler**

Run: `grep -n "CHAT_TOOL_CALL_COMPLETED\|CHAT_STREAM_ERROR" frontend/src/features/chat/useChatStream.ts`

Expected: Line numbers. Read both handlers fully.

- [ ] **Step 2: Write the failing tests**

Create `frontend/src/features/chat/__tests__/useChatStream.test.ts`. The exact test scaffolding depends on how existing tests exercise `useChatStream`. If there is no existing test file for it, write a minimal one that imports the hook and simulates events by calling the internal event handler directly (look at how `chatStore.test.ts` bypasses React-rendering concerns).

If testing the hook in isolation is awkward, instead test the **pure event-handler function** that processes an event. That function may need to be extracted if it is currently a closure inside the hook. If so, extract it to a small module-local helper that takes `(event, getStore, sendMessage)` and is exported for testing.

Tests to add:

```typescript
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useChatStore } from '../chatStore'
import { handleChatEvent } from '../useChatStream'  // extract this if needed

describe('useChatStream — CHAT_TOOL_CALL_COMPLETED', () => {
  beforeEach(() => {
    useChatStore.setState({
      streamingArtefactRefs: [],
      correlationId: 'c1',
      activeToolCalls: [],
    } as any)
  })

  it('appends artefact_ref to streamingArtefactRefs when present', () => {
    const event = {
      type: 'chat.tool_call.completed',
      correlation_id: 'c1',
      payload: {
        tool_call_id: 'tc1',
        tool_name: 'create_artefact',
        success: true,
        artefact_ref: {
          artefact_id: 'a1',
          handle: 'h1',
          title: 't1',
          artefact_type: 'code',
          operation: 'create',
        },
      },
    }
    handleChatEvent(event as any, vi.fn(), 's1')
    expect(useChatStore.getState().streamingArtefactRefs).toHaveLength(1)
  })

  it('does not touch streamingArtefactRefs when artefact_ref is absent', () => {
    const event = {
      type: 'chat.tool_call.completed',
      correlation_id: 'c1',
      payload: {
        tool_call_id: 'tc2',
        tool_name: 'web_search',
        success: true,
      },
    }
    handleChatEvent(event as any, vi.fn(), 's1')
    expect(useChatStore.getState().streamingArtefactRefs).toEqual([])
  })
})

describe('useChatStream — CHAT_STREAM_ERROR with refusal', () => {
  beforeEach(() => {
    useChatStore.setState({
      correlationId: 'c1',
      streamingRefusalText: null,
    } as any)
  })

  it('sets toast title to "Request declined" when error_code=refusal', () => {
    const addNotification = vi.fn()
    // Mock the notification store
    vi.doMock('../../../core/store/notificationStore', () => ({
      useNotificationStore: {
        getState: () => ({ addNotification }),
      },
    }))

    const event = {
      type: 'chat.stream.error',
      correlation_id: 'c1',
      payload: {
        error_code: 'refusal',
        recoverable: true,
        user_message: 'Model declined your request.',
      },
    }
    handleChatEvent(event as any, vi.fn(), 's1')

    expect(addNotification).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Request declined' })
    )
    // streamingRefusalText was set from user_message
    expect(useChatStore.getState().streamingRefusalText).toBe('Model declined your request.')
  })
})
```

If extracting `handleChatEvent` is non-trivial, an alternative is to render the hook inside a test component using `@testing-library/react-hooks` or a tiny wrapper that calls the WebSocket event dispatcher path. Pick whichever approach is less invasive given the real useChatStream structure.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd frontend && pnpm vitest run src/features/chat/__tests__/useChatStream.test.ts`

Expected: FAIL.

- [ ] **Step 4: Extend `useChatStream.ts`**

In the `CHAT_TOOL_CALL_COMPLETED` handler, after `getStore().completeToolCall(...)`, add:

```typescript
const artefactRef = p.artefact_ref as ArtefactRef | null | undefined
if (artefactRef) {
  getStore().appendArtefactRef(artefactRef)
}
```

Import `ArtefactRef` from `../../core/api/chat` at the top of the file if not already present.

In the `CHAT_STREAM_ERROR` handler, replace the existing `const title = ...` calculation with:

```typescript
const title = (() => {
  if (errorCode === 'refusal') return 'Request declined'
  if (recoverable) return 'Response interrupted'
  return 'Error'
})()
```

Still inside the `CHAT_STREAM_ERROR` handler, alongside the existing `getStore().setError({...})` call, add:

```typescript
if (errorCode === 'refusal') {
  getStore().setStreamingRefusalText(userMessage)
}
```

If the tests required extracting `handleChatEvent` as a named export, do that extraction here as a minimal refactor: pull the big `switch` block out of the hook closure into a module-local function that takes the necessary dependencies as arguments, and re-export it. The hook then calls this function per event.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd frontend && pnpm vitest run src/features/chat/__tests__/useChatStream.test.ts`

Expected: PASS.

- [ ] **Step 6: Run the rest of the chat tests to check regressions**

Run: `cd frontend && pnpm vitest run src/features/chat`

Expected: All tests pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/chat/useChatStream.ts frontend/src/features/chat/__tests__/useChatStream.test.ts
git commit -m "$(cat <<'EOF'
Wire tool-call artefact capture and refusal toast in useChatStream

The CHAT_TOOL_CALL_COMPLETED handler now forwards an optional
artefact_ref payload field into the chat store's streaming slice.
The CHAT_STREAM_ERROR handler specialises the toast title to
'Request declined' for error_code='refusal' and stores the
user_message into streamingRefusalText so the live message can
show it without waiting for a refresh.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: Frontend — `useChatStream` stream-ended assembly

**Files:**
- Modify: `frontend/src/features/chat/useChatStream.ts`
- Test: `frontend/src/features/chat/__tests__/useChatStream.test.ts`

- [ ] **Step 1: Read the existing `CHAT_STREAM_ENDED` handler**

Run: `grep -n "CHAT_STREAM_ENDED\|finishStreaming" frontend/src/features/chat/useChatStream.ts`

Expected: The block (currently around lines 103–119) that assembles the final message and calls `finishStreaming`.

- [ ] **Step 2: Write the failing tests**

Add to `frontend/src/features/chat/__tests__/useChatStream.test.ts`:

```typescript
describe('useChatStream — CHAT_STREAM_ENDED refusal and artefact persistence', () => {
  beforeEach(() => {
    useChatStore.setState({
      correlationId: 'c1',
      streamingContent: '',
      streamingThinking: '',
      streamingWebSearchContext: [],
      streamingKnowledgeContext: [],
      streamingArtefactRefs: [],
      streamingRefusalText: null,
      messages: [],
      activeToolCalls: [],
      contextStatus: 'green',
      contextFillPercentage: 0,
    } as any)
  })

  it('assembles final message with refused status and refusal_text', () => {
    useChatStore.setState({
      streamingContent: '',
      streamingRefusalText: 'declined',
    } as any)
    const event = {
      type: 'chat.stream.ended',
      correlation_id: 'c1',
      payload: {
        message_id: 'm1',
        status: 'refused',
        context_status: 'green',
        context_fill_percentage: 0.1,
      },
    }
    handleChatEvent(event as any, vi.fn(), 's1')
    const messages = useChatStore.getState().messages
    expect(messages).toHaveLength(1)
    expect(messages[0].status).toBe('refused')
    expect(messages[0].refusal_text).toBe('declined')
  })

  it('persists content-less refused messages on finish', () => {
    useChatStore.setState({
      streamingContent: '',
      streamingThinking: '',
      streamingRefusalText: 'declined',
    } as any)
    const event = {
      type: 'chat.stream.ended',
      correlation_id: 'c1',
      payload: {
        message_id: 'm1',
        status: 'refused',
        context_status: 'green',
        context_fill_percentage: 0,
      },
    }
    handleChatEvent(event as any, vi.fn(), 's1')
    expect(useChatStore.getState().messages).toHaveLength(1)
  })

  it('attaches streamingArtefactRefs to the final message', () => {
    useChatStore.setState({
      streamingContent: 'body',
      streamingArtefactRefs: [
        {
          artefact_id: 'a1',
          handle: 'h1',
          title: 't1',
          artefact_type: 'code',
          operation: 'create',
        },
      ],
    } as any)
    const event = {
      type: 'chat.stream.ended',
      correlation_id: 'c1',
      payload: {
        message_id: 'm1',
        status: 'completed',
        context_status: 'green',
        context_fill_percentage: 0,
      },
    }
    handleChatEvent(event as any, vi.fn(), 's1')
    const messages = useChatStore.getState().messages
    expect(messages[0].artefact_refs).toHaveLength(1)
    expect(messages[0].artefact_refs![0].handle).toBe('h1')
  })
})
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd frontend && pnpm vitest run src/features/chat/__tests__/useChatStream.test.ts`

Expected: FAIL — content-less refused messages are not persisted and new fields are missing from the final message.

- [ ] **Step 4: Extend the `CHAT_STREAM_ENDED` handler**

Inside `useChatStream.ts`, replace the current stream-ended payload assembly with the extended version:

```typescript
case Topics.CHAT_STREAM_ENDED: {
  if (event.correlation_id !== getStore().correlationId) return
  const backendMessageId = p.message_id as string | undefined
  const content = getStore().streamingContent
  const thinking = getStore().streamingThinking
  const webSearchContext = getStore().streamingWebSearchContext
  const knowledgeContext = getStore().streamingKnowledgeContext
  const artefactRefs = getStore().streamingArtefactRefs
  const refusalText = getStore().streamingRefusalText

  const rawStatus = p.status as string | undefined
  const messageStatus: 'completed' | 'aborted' | 'refused' =
    rawStatus === 'refused'
      ? 'refused'
      : rawStatus === 'aborted'
        ? 'aborted'
        : 'completed'

  const contextStatus = p.context_status as 'green' | 'yellow' | 'orange' | 'red'
  const fillPercentage = (p.context_fill_percentage as number) ?? 0

  if (backendMessageId && (content || thinking || messageStatus === 'refused')) {
    getStore().finishStreaming(
      {
        id: backendMessageId,
        session_id: sessionId,
        role: 'assistant',
        content,
        thinking: thinking || null,
        token_count: 0,
        attachments: null,
        web_search_context: webSearchContext.length > 0 ? webSearchContext : null,
        knowledge_context: knowledgeContext.length > 0 ? knowledgeContext : null,
        artefact_refs: artefactRefs.length > 0 ? artefactRefs : null,
        refusal_text: refusalText || null,
        created_at: new Date().toISOString(),
        status: messageStatus,
      },
      contextStatus,
      fillPercentage,
    )
  }
  break
}
```

Preserve any existing logic around session expiration or special-case handling that already lived inside this case arm — do not delete code you did not author.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && pnpm vitest run src/features/chat/__tests__/useChatStream.test.ts`

Expected: All new tests pass.

- [ ] **Step 6: Run the full chat test bucket**

Run: `cd frontend && pnpm vitest run src/features/chat`

Expected: All pass.

- [ ] **Step 7: Type-check + build**

Run: `cd frontend && pnpm tsc --noEmit && pnpm run build`

Expected: Clean type check and successful build.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/chat/useChatStream.ts frontend/src/features/chat/__tests__/useChatStream.test.ts
git commit -m "$(cat <<'EOF'
Assemble refused and artefact-rich final messages in CHAT_STREAM_ENDED

Extends the stream-ended handler so content-less refused messages
are still pushed into the store (matching the backend's 'or status
== refused' guard), and the final message carries the persisted
artefact_refs and refusal_text accumulated during the stream. This
means the user sees a refusal with a red band and persisted artefact
cards immediately when the stream ends, without waiting for a
page refresh.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: Frontend integration smoke test

**Files:** None modified.

- [ ] **Step 1: Run the full frontend test suite**

Run: `cd frontend && pnpm vitest run`

Expected: All tests pass. If anything in another feature area fails, read the failure and decide whether it is a true regression.

- [ ] **Step 2: Full build**

Run: `cd frontend && pnpm run build`

Expected: Successful build, no type errors, no lint errors. If Vite emits warnings that predate this work, ignore them.

- [ ] **Step 3: Commit any incidental fixes**

If fixes were needed, commit with a message describing them. Otherwise proceed.

---

## Task 16: Manual verification

**Files:** `MANUAL-TESTS-REFUSAL-AND-ARTEFACTS.md` (used as a checklist, not modified)

This task is performed by a human (Chris). The subagent cannot tick these boxes.

- [ ] **Step 1: Start backend and frontend locally**

Run whatever development commands the project uses — likely `docker compose up` for backend dependencies and `cd frontend && pnpm dev` for the frontend.

- [ ] **Step 2: Work through `MANUAL-TESTS-REFUSAL-AND-ARTEFACTS.md`**

Open the file. Tick items as you verify them:
- Section A (Refusal happy path, regenerate, content-less fallback)
- Section B (Artefact create, update, multi-operation, aborted-stream persistence)
- Section C (Regression: completed, aborted without artefact, slow, web search, knowledge search)
- Section D (Schub 4.1 usage piggyback)

- [ ] **Step 3: Note the real `done_reason` values observed**

Fill in the Observability Summary section at the bottom of the manual test file with any real `done_reason` values seen during testing. These will later inform whether `_REFUSAL_REASONS` needs extension.

- [ ] **Step 4: If issues are found, file a followup**

If manual verification surfaces a bug that is not a simple fix, do not patch it in this branch — note it and proceed. The fix can be a follow-up commit or a new task. If the bug is trivial and clearly in-scope, fix it and add a commit.

- [ ] **Step 5: Commit the annotated manual test file**

After verification passes, commit the filled-in checklist so the sign-off is preserved in git:

```bash
git add MANUAL-TESTS-REFUSAL-AND-ARTEFACTS.md
git commit -m "Record manual test sign-off for refusal detection and artefact persistence"
```

---

## Task 17: Clean up Schub 4.1 in followups and merge

**Files:**
- Modify: `STREAM-ABORT-FOLLOWUPS.md` — remove Schub 4.1 (now done) but keep Schub 4.2

- [ ] **Step 1: Edit `STREAM-ABORT-FOLLOWUPS.md`**

Remove the entire `### 4.1 — `usage` wird nicht persistiert` section (the heading and all content up to but not including `### 4.2`). Leave 4.2 and the surrounding Schub 4 header intact.

If the Schub 4 header becomes awkward because only 4.2 is left, reword the intro paragraph under `## Schub 4 — Nachzügler aus Schub 1` to reflect that only one item remains:

```markdown
## Schub 4 — Nachzügler aus Schub 1

Ein Punkt, der während der Code-Erkundung für Schub 2/3 aufgefallen ist und noch nicht umgesetzt wurde. Kein Beta-Blocker, gehört aber auf die Liste, damit es nicht verloren geht.
```

Then keep the existing `### 4.2 — Gutter-State-Machine ist nicht test-injizierbar` section unchanged.

- [ ] **Step 2: Commit the followups update**

```bash
git add STREAM-ABORT-FOLLOWUPS.md
git commit -m "$(cat <<'EOF'
Remove Schub 4.1 from followups (usage persistence now shipped)

Usage persistence was piggybacked into the Schub 2/3 merge and is
now live. Only Schub 4.2 (gutter clock test-injection seam) remains
deferred.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 3: Merge to master (or confirm already on master)**

Per the user's defaults (CLAUDE.md: "Please always merge to master after implementation"), this step completes the plan. If implementation happened on a feature branch or worktree:

```bash
git checkout master
git merge --no-ff <feature-branch-name>
```

If implementation happened directly on master, this step is a no-op — all the commits are already there.

Expected: `git log --oneline -20` shows the full sequence of Task 1–17 commits on master, culminating in the followups cleanup commit.

- [ ] **Step 4: Final smoke**

Run one final build on master to make sure the merge did not introduce conflicts or breakage:

```bash
uv run pytest tests/ -q
cd frontend && pnpm tsc --noEmit && pnpm vitest run && pnpm run build
```

Expected: All green.

---

## Self-review notes for the planner

After writing the plan, run the self-review checklist from the writing-plans skill:

**Spec coverage**: Every section of the design spec maps to a task:
- Spec §1 (shared contracts) → Tasks 1, 2
- Spec §2 (StreamRefused event) → Task 3
- Spec §3 (Ollama adapter done_reason) → Task 4
- Spec §4 (Inference layer: match arm + artefact capture + save_fn extension) → Tasks 5, 6
- Spec §5 (Orchestrator: context filter + save_fn closure) → Task 7
- Spec §6 (Repository: save_message + message_to_dto) → Task 8
- Spec §7 (Frontend types) → Task 2
- Spec §8 (AssistantMessage) → Task 10
- Spec §9 (MessageList) → Task 11
- Spec §10 (chatStore + useChatStream) → Tasks 12, 13, 14
- Testing (Backend unit, Frontend unit) → Inline TDD steps in each task
- Manual verification → Task 16
- Migration & Rollout → Task 17 (merge) and Task 15/9 (integration smoke)
- Schub 4.1 piggyback → Task 7 (closure forwarding), Task 8 (save_message), Task 17 (followups cleanup)

**Placeholder scan**: Plan contains concrete code in every step that changes code. No TBDs, no "handle edge cases" vague instructions.

**Type consistency**: `ArtefactRefDto` (Python) matches `ArtefactRef` (TypeScript) field-for-field. `streamingArtefactRefs`, `streamingRefusalText`, `appendArtefactRef`, `setStreamingRefusalText` names consistent throughout. `_REFUSAL_FALLBACK_TEXT` (backend) and `REFUSAL_FALLBACK_TEXT` (frontend) both resolve to the same literal string "The model declined this request.".
