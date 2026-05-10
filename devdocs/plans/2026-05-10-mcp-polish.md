# MCP Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tool-call pills in the chat UI show what each tool returned, and the
backend MCP client speaks the Streamable HTTP transport (`Accept` header +
SSE response handling) so it works against FastMCP-default servers.

**Architecture:** Two coupled but independent changes on the same feature
branch (`feat/mcp-polish`). Part A propagates a new optional `result_content`
field through `ToolCallRefDto`/`TimelineEntryToolCall`/`ChatToolCallCompleted
Event` and renders it in the existing `ToolCallPills` popover. Part B
rewrites `_mcp_executor.py` to send `Accept: application/json,
text/event-stream` and dispatch on the response `Content-Type` (parsing SSE
when needed).

**Tech Stack:** Python 3.12 / FastAPI / Pydantic v2 / httpx / pytest;
React / TypeScript / Vitest. Pill rendering uses inline-style Tailwind
(no design-system tokens here).

**Spec:** `devdocs/specs/2026-05-10-mcp-pills-result-and-streamable-http-design.md`

**Branch:** `feat/mcp-polish` (already created)

---

## Task ordering rationale

Part A first (DTO → event → backend wiring → frontend wiring → render), then
Part B (header → SSE dispatch). Part B does not depend on Part A but is a
clean self-contained block at the end. Part A is built bottom-up so each
intermediate commit type-checks.

---

## Part A — Pills with Result

### Task 1: Add `result_content` to shared DTOs

**Files:**
- Modify: `shared/dtos/chat.py:95-101` (ToolCallRefDto)
- Modify: `shared/dtos/chat.py:143-152` (TimelineEntryToolCall)
- Modify: `frontend/src/core/api/chat.ts:86-93` (ToolCallRef interface)
- Modify: `frontend/src/core/api/chat.ts:116-124` (TimelineEntryToolCall interface)

- [ ] **Step 1: Extend ToolCallRefDto in `shared/dtos/chat.py`**

Replace the existing class body:

```python
class ToolCallRefDto(BaseModel):
    """Metadata for a single tool call executed during inference."""
    tool_call_id: str
    tool_name: str
    arguments: dict
    success: bool
    moderated_count: int = 0
    result_content: str | None = None
```

- [ ] **Step 2: Extend TimelineEntryToolCall in `shared/dtos/chat.py`**

Replace the existing class body:

```python
class TimelineEntryToolCall(BaseModel):
    """Generic tool call — used for tools without a specialised renderer
    and for any failed tool call regardless of which tool it was."""
    kind: Literal["tool_call"] = "tool_call"
    seq: int
    tool_call_id: str
    tool_name: str
    arguments: dict
    success: bool
    moderated_count: int = 0
    result_content: str | None = None
```

- [ ] **Step 3: Mirror in TS — `frontend/src/core/api/chat.ts:86-93`**

Replace the `ToolCallRef` interface:

```typescript
interface ToolCallRef {
  tool_call_id: string
  tool_name: string
  arguments: Record<string, unknown>
  success: boolean
  /** Number of image slots rejected by the content-moderation filter. */
  moderated_count?: number
  /** Tool result text — shown in the expanded pill popover. Null for
   * historical messages persisted before this field existed and for
   * live calls that have not yet returned. */
  result_content?: string | null
}
```

- [ ] **Step 4: Mirror in TS — `frontend/src/core/api/chat.ts:116-124`**

Replace the `TimelineEntryToolCall` interface:

```typescript
interface TimelineEntryToolCall {
  kind: 'tool_call'
  seq: number
  tool_call_id: string
  tool_name: string
  arguments: Record<string, unknown>
  success: boolean
  moderated_count?: number
  result_content?: string | null
}
```

- [ ] **Step 5: Verify backend syntax**

Run: `uv run python -m py_compile shared/dtos/chat.py`
Expected: no output (compile succeeds).

- [ ] **Step 6: Verify TS type-check**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add shared/dtos/chat.py frontend/src/core/api/chat.ts
git commit -m "Add result_content field to ToolCallRefDto and TimelineEntryToolCall"
```

---

### Task 2: Add `result_content` to `ChatToolCallCompletedEvent`

**Files:**
- Modify: `shared/events/chat.py:168-180`

- [ ] **Step 1: Extend the event in `shared/events/chat.py`**

Replace the existing class body at line 168:

```python
class ChatToolCallCompletedEvent(BaseModel):
    type: str = "chat.tool_call.completed"
    correlation_id: str
    tool_call_id: str
    tool_name: str
    success: bool
    artefact_ref: ArtefactRefDto | None = None
    # Populated for generate_image tool calls so the frontend can render
    # the inline image block live (without waiting for a session reload).
    # Mirrors the artefact_ref pattern.
    image_refs: list[ImageRefDto] | None = None
    moderated_count: int = 0
    # Tool result text — carried live so the chat pill can show the
    # Response section the moment the tool completes, instead of only
    # after a session reload. None when the tool produced no usable
    # text (rare; safe default).
    result_content: str | None = None
    timestamp: datetime
```

- [ ] **Step 2: Verify syntax**

Run: `uv run python -m py_compile shared/events/chat.py`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add shared/events/chat.py
git commit -m "Add result_content to ChatToolCallCompletedEvent for live pill updates"
```

---

### Task 3: Backend wiring — propagate `result_str` into event + timeline entry

**Files:**
- Modify: `backend/modules/chat/_inference.py:101-163` (make_timeline_entry signature + branches)
- Modify: `backend/modules/chat/_inference.py:631-640` (ChatToolCallCompletedEvent emit)
- Modify: `backend/modules/chat/_inference.py:693-704` (events.append call)
- Test: `tests/test_inference_result_content.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_inference_result_content.py`:

```python
"""Result-content propagation through make_timeline_entry."""

from backend.modules.chat._inference import make_timeline_entry
from shared.dtos.chat import TimelineEntryToolCall


def test_make_timeline_entry_carries_result_content_on_success():
    entry = make_timeline_entry(
        seq=0,
        tool_name="some_unknown_tool",   # falls through to generic tool_call branch
        tool_call_id="tc-1",
        arguments={"q": "x"},
        success=True,
        result_content="42",
    )
    assert isinstance(entry, TimelineEntryToolCall)
    assert entry.result_content == "42"


def test_make_timeline_entry_carries_result_content_on_failure():
    entry = make_timeline_entry(
        seq=0,
        tool_name="some_unknown_tool",
        tool_call_id="tc-2",
        arguments={"q": "x"},
        success=False,
        result_content="boom: tool not found",
    )
    assert isinstance(entry, TimelineEntryToolCall)
    assert entry.result_content == "boom: tool not found"


def test_make_timeline_entry_defaults_result_content_to_none():
    """Old call sites without result_content keep working."""
    entry = make_timeline_entry(
        seq=0,
        tool_name="some_unknown_tool",
        tool_call_id="tc-3",
        arguments={},
        success=True,
    )
    assert isinstance(entry, TimelineEntryToolCall)
    assert entry.result_content is None
```

- [ ] **Step 2: Run the test, expect failure**

Run: `PYTHONPATH=. uv run pytest tests/test_inference_result_content.py -v`
Expected: FAIL with `TypeError: make_timeline_entry() got an unexpected keyword argument 'result_content'`.

- [ ] **Step 3: Update `make_timeline_entry()` in `backend/modules/chat/_inference.py:101`**

Add the new parameter and propagate it into both `TimelineEntryToolCall`
construction sites. Replace the function body:

```python
def make_timeline_entry(
    *,
    seq: int,
    tool_name: str,
    tool_call_id: str,
    arguments: dict,
    success: bool,
    moderated_count: int = 0,
    knowledge_results: list | None = None,
    web_items: list | None = None,
    artefact_ref: ArtefactRefDto | None = None,
    image_refs: list | None = None,
    result_content: str | None = None,
):
    """Map one completed tool call to its TimelineEntry variant.

    A failed tool always becomes a generic ``tool_call`` entry, regardless
    of which tool it was — empty knowledge/web pills would be confusing
    and a failed image generation has no refs to render.

    ``result_content`` is the text the tool returned (or its error
    message). Only carried on the generic ``tool_call`` entry — typed
    entries (knowledge / web / artefact / image) render their own
    structured payload and ignore the parameter.
    """
    if not success:
        return TimelineEntryToolCall(
            seq=seq,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments=arguments,
            success=False,
            moderated_count=moderated_count,
            result_content=result_content,
        )

    if tool_name == "knowledge_search":
        items = [
            r if isinstance(r, KnowledgeContextItem)
            else KnowledgeContextItem.model_validate(r)
            for r in (knowledge_results or [])
        ]
        return TimelineEntryKnowledgeSearch(seq=seq, items=items)

    if tool_name in ("web_search", "web_fetch"):
        items = [
            w if isinstance(w, WebSearchContextItemDto)
            else WebSearchContextItemDto.model_validate(w)
            for w in (web_items or [])
        ]
        return TimelineEntryWebSearch(seq=seq, items=items)

    if tool_name in ("create_artefact", "update_artefact") and artefact_ref is not None:
        return TimelineEntryArtefact(seq=seq, ref=artefact_ref)

    if tool_name == "generate_image":
        return TimelineEntryImage(
            seq=seq,
            refs=list(image_refs or []),
            moderated_count=moderated_count,
        )

    return TimelineEntryToolCall(
        seq=seq,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        arguments=arguments,
        success=success,
        moderated_count=moderated_count,
        result_content=result_content,
    )
```

- [ ] **Step 4: Run the test, expect pass**

Run: `PYTHONPATH=. uv run pytest tests/test_inference_result_content.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Update the `events.append(make_timeline_entry(...))` call at line ~693**

In `backend/modules/chat/_inference.py`, locate the existing block:

```python
events.append(make_timeline_entry(
    seq=next_seq,
    tool_name=tc.name,
    tool_call_id=tc.id,
    arguments=arguments,
    success=tool_success,
    moderated_count=moderated_count,
    knowledge_results=knowledge_items_for_entry,
    web_items=web_items_for_entry,
    artefact_ref=ref_for_event,
    image_refs=image_refs_for_entry,
))
```

Add the new keyword argument at the end:

```python
events.append(make_timeline_entry(
    seq=next_seq,
    tool_name=tc.name,
    tool_call_id=tc.id,
    arguments=arguments,
    success=tool_success,
    moderated_count=moderated_count,
    knowledge_results=knowledge_items_for_entry,
    web_items=web_items_for_entry,
    artefact_ref=ref_for_event,
    image_refs=image_refs_for_entry,
    result_content=result_str,
))
```

`result_str` is in scope at this point — it was set at lines 542 / 545 /
555 / 568 (recoverable error or executor return).

- [ ] **Step 6: Update the `ChatToolCallCompletedEvent` emit at line ~631**

Locate the existing block:

```python
await emit_fn(ChatToolCallCompletedEvent(
    correlation_id=correlation_id,
    tool_call_id=tc.id,
    tool_name=tc.name,
    success=tool_success,
    artefact_ref=ref_for_event,
    image_refs=image_refs_for_event,
    moderated_count=moderated_count,
    timestamp=datetime.now(timezone.utc),
))
```

Add the new keyword argument:

```python
await emit_fn(ChatToolCallCompletedEvent(
    correlation_id=correlation_id,
    tool_call_id=tc.id,
    tool_name=tc.name,
    success=tool_success,
    artefact_ref=ref_for_event,
    image_refs=image_refs_for_event,
    moderated_count=moderated_count,
    result_content=result_str,
    timestamp=datetime.now(timezone.utc),
))
```

- [ ] **Step 7: Verify backend syntax**

Run: `uv run python -m py_compile backend/modules/chat/_inference.py`
Expected: no output.

- [ ] **Step 8: Run the inference-runner suite (sanity)**

Run: `PYTHONPATH=. uv run pytest tests/test_inference_runner.py tests/test_inference_result_content.py -v`
Expected: PASS for the new tests; the existing inference suite must remain
green. (`make_timeline_entry` keeps a backwards-compatible default for
`result_content=None`, so callers that don't pass it stay valid.)

- [ ] **Step 9: Commit**

```bash
git add backend/modules/chat/_inference.py tests/test_inference_result_content.py
git commit -m "Propagate tool result_content into TimelineEntry and live event"
```

---

### Task 4: Frontend wiring — `useChatStream` forwards `result_content`

**Files:**
- Modify: `frontend/src/features/chat/useChatStream.ts:144-217`
- Test: `frontend/src/features/chat/__tests__/useChatStream.test.ts` (extend)

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/features/chat/__tests__/useChatStream.test.ts`
inside the existing `describe(...)` block (find the closing `})` of the
suite and add before it). The test seeds a stream with a matching
`correlationId` and asserts the appended TimelineEntry carries
`result_content`:

```typescript
  it('forwards result_content from tool_call.completed into the TimelineEntry', () => {
    seedStream({ correlationId: 'c1', isStreaming: true })
    const event = makeEvent({
      type: 'chat.tool_call.completed',
      correlation_id: 'c1',
      payload: {
        tool_call_id: 'tc-1',
        tool_name: 'echo',
        success: true,
        arguments: { msg: 'hi' },
        result_content: 'echo: hi',
      },
    } as Partial<BaseEvent> & { type: string })
    handleChatEvent(event, SESSION_ID, mockSendMessage)
    const events = useChatStore.getState().streamsBySession.get(SESSION_ID)?.streamingEvents ?? []
    const entry = events[0] as Extract<TimelineEntry, { kind: 'tool_call' }>
    expect(entry.kind).toBe('tool_call')
    expect(entry.result_content).toBe('echo: hi')
  })

  it('forwards result_content on a failed tool call', () => {
    seedStream({ correlationId: 'c1', isStreaming: true })
    const event = makeEvent({
      type: 'chat.tool_call.completed',
      correlation_id: 'c1',
      payload: {
        tool_call_id: 'tc-2',
        tool_name: 'broken',
        success: false,
        arguments: {},
        result_content: 'Error: tool blew up',
      },
    } as Partial<BaseEvent> & { type: string })
    handleChatEvent(event, SESSION_ID, mockSendMessage)
    const events = useChatStore.getState().streamsBySession.get(SESSION_ID)?.streamingEvents ?? []
    const entry = events[0] as Extract<TimelineEntry, { kind: 'tool_call' }>
    expect(entry.kind).toBe('tool_call')
    expect(entry.success).toBe(false)
    expect(entry.result_content).toBe('Error: tool blew up')
  })
```

- [ ] **Step 2: Run the test, expect failure**

Run: `cd frontend && pnpm vitest run src/features/chat/__tests__/useChatStream.test.ts -t "result_content"`
Expected: FAIL — both new tests assert undefined / mismatched.

- [ ] **Step 3: Update `useChatStream.ts:144-217`**

In the `Topics.CHAT_TOOL_CALL_COMPLETED` case, read the new field and
pass it into both branches that build a `tool_call` TimelineEntry.

Right after the existing payload extraction (line ~154 area), add:

```typescript
const resultContent = (p.result_content as string | null | undefined) ?? null
```

Then in the failure branch (around line 162) replace the entry literal:

```typescript
const entry: TimelineEntry = {
  kind: 'tool_call',
  seq: 0,
  tool_call_id: toolCallId,
  tool_name: toolName,
  arguments: args,
  success: false,
  moderated_count: moderatedCount,
  result_content: resultContent,
}
```

And in the generic-success branch (around line 205):

```typescript
const entry: TimelineEntry = {
  kind: 'tool_call',
  seq: 0,
  tool_call_id: toolCallId,
  tool_name: toolName,
  arguments: args,
  success,
  moderated_count: moderatedCount,
  result_content: resultContent,
}
```

The artefact / generate_image branches stay unchanged — they render
typed entries without a Response section.

- [ ] **Step 4: Run the test, expect pass**

Run: `cd frontend && pnpm vitest run src/features/chat/__tests__/useChatStream.test.ts -t "result_content"`
Expected: PASS — both tests green.

- [ ] **Step 5: Run the full useChatStream suite (regression)**

Run: `cd frontend && pnpm vitest run src/features/chat/__tests__/useChatStream.test.ts`
Expected: PASS — no regressions.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/chat/useChatStream.ts frontend/src/features/chat/__tests__/useChatStream.test.ts
git commit -m "Forward result_content from tool_call.completed event into timeline entries"
```

---

### Task 5: Frontend rendering — `ToolCallPills` shows Request + Response

**Files:**
- Modify: `frontend/src/features/chat/ToolCallPills.tsx` (whole file)
- Modify: `frontend/src/features/chat/MessageList.tsx:120-131` (forward result_content into ref)
- Test: `frontend/src/features/chat/__tests__/ToolCallPills.test.tsx` (new)

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/features/chat/__tests__/ToolCallPills.test.tsx`:

```typescript
import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ToolCallPills } from '../ToolCallPills'
import type { ToolCallRef } from '../../../core/api/chat'

function makeRef(overrides: Partial<ToolCallRef> = {}): ToolCallRef {
  return {
    tool_call_id: 'tc-1',
    tool_name: 'gw__echo',
    arguments: { msg: 'hi' },
    success: true,
    result_content: null,
    ...overrides,
  }
}

describe('ToolCallPills', () => {
  it('renders Request and Response sections when result_content is set', () => {
    render(<ToolCallPills toolCalls={[makeRef({ result_content: 'echo: hi' })]} />)
    fireEvent.click(screen.getByRole('button'))
    expect(screen.getByText('Request')).toBeInTheDocument()
    expect(screen.getByText('Response')).toBeInTheDocument()
    expect(screen.getByText(/echo: hi/)).toBeInTheDocument()
    expect(screen.getByText(/msg: hi/)).toBeInTheDocument()
  })

  it('omits Response section when result_content is null', () => {
    render(<ToolCallPills toolCalls={[makeRef({ result_content: null })]} />)
    fireEvent.click(screen.getByRole('button'))
    expect(screen.getByText('Request')).toBeInTheDocument()
    expect(screen.queryByText('Response')).not.toBeInTheDocument()
  })

  it('renders Response on a failed call when result_content is set', () => {
    render(<ToolCallPills toolCalls={[makeRef({
      success: false,
      result_content: 'Error: boom',
    })]} />)
    fireEvent.click(screen.getByRole('button'))
    expect(screen.getByText('Response')).toBeInTheDocument()
    expect(screen.getByText(/Error: boom/)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run the tests, expect failure**

Run: `cd frontend && pnpm vitest run src/features/chat/__tests__/ToolCallPills.test.tsx`
Expected: FAIL — Request/Response labels do not exist yet.

- [ ] **Step 3: Rewrite `ToolCallPills.tsx`**

Replace the file with:

```typescript
import { useState } from 'react'
import type { ToolCallRef } from '../../core/api/chat'

interface ToolCallPillsProps {
  toolCalls: ToolCallRef[]
}

function ToolIcon() {
  return (
    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
    </svg>
  )
}

function formatArgs(args: Record<string, unknown>): string {
  const entries = Object.entries(args)
  if (entries.length === 0) return '(no arguments)'
  return entries
    .map(([k, v]) => {
      const val = typeof v === 'string' ? v : JSON.stringify(v)
      const display = val.length > 60 ? val.slice(0, 60) + '...' : val
      return `${k}: ${display}`
    })
    .join('\n')
}

function displayName(toolName: string): string {
  const parts = toolName.split('__')
  return parts.length > 1 ? parts.slice(1).join('__') : toolName
}

export function ToolCallPills({ toolCalls }: ToolCallPillsProps) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null)

  if (toolCalls.length === 0) return null

  return (
    <div className="mb-2 flex flex-wrap gap-1.5">
      {toolCalls.map((tc, idx) => {
        const colour = tc.success ? '245,194,131' : '243,139,168'
        const hasResult = tc.result_content != null && tc.result_content !== ''
        return (
          <div key={tc.tool_call_id} className="relative">
            <button
              type="button"
              onClick={() => setExpandedIdx(expandedIdx === idx ? null : idx)}
              className="flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] transition-opacity hover:opacity-90"
              style={{
                background: `rgba(${colour},0.12)`,
                border: `1px solid rgba(${colour},0.25)`,
                color: `rgba(${colour},0.9)`,
                fontFamily: "'Courier New', monospace",
              }}
            >
              <ToolIcon />
              {displayName(tc.tool_name)}
            </button>
            {expandedIdx === idx && (
              <div
                className="absolute left-0 top-full z-20 mt-1 min-w-[280px] max-w-[400px] rounded-lg p-3"
                style={{
                  background: 'rgba(20, 18, 28, 0.98)',
                  border: `1px solid rgba(${colour},0.25)`,
                  boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
                  maxHeight: 320,
                  overflowY: 'auto',
                }}
              >
                <div className="mb-1.5 text-[10px] font-medium" style={{ color: `rgba(${colour},0.9)` }}>
                  {tc.tool_name}
                </div>
                <div className="mb-1 text-[10px] font-medium" style={{ color: `rgba(${colour},0.9)` }}>
                  Request
                </div>
                <pre
                  className="whitespace-pre-wrap text-[11px] leading-relaxed text-white/50"
                  style={{ fontFamily: "'Courier New', monospace" }}
                >
                  {formatArgs(tc.arguments)}
                </pre>
                {hasResult && (
                  <>
                    <div
                      className="mt-2 mb-1 text-[10px] font-medium"
                      style={{ color: `rgba(${colour},0.9)` }}
                    >
                      Response
                    </div>
                    <pre
                      className="whitespace-pre-wrap text-[11px] leading-relaxed text-white/50"
                      style={{ fontFamily: "'Courier New', monospace" }}
                    >
                      {tc.result_content}
                    </pre>
                  </>
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
```

- [ ] **Step 4: Update the timeline-entry → ref converter in `MessageList.tsx`**

In `frontend/src/features/chat/MessageList.tsx:120-131`, the existing
`tool_call` case strips `result_content` when wrapping into a
`ToolCallRef`. Add the field:

```typescript
case 'tool_call': {
  // ToolCallPills consumes the ToolCallRef shape — the timeline entry
  // already carries the same identifying fields, just re-wrapped.
  const ref: ToolCallRef = {
    tool_call_id: entry.tool_call_id,
    tool_name: entry.tool_name,
    arguments: entry.arguments,
    success: entry.success,
    moderated_count: entry.moderated_count,
    result_content: entry.result_content ?? null,
  }
  return <ToolCallPills key={k} toolCalls={[ref]} />
}
```

- [ ] **Step 5: Run the pill tests, expect pass**

Run: `cd frontend && pnpm vitest run src/features/chat/__tests__/ToolCallPills.test.tsx`
Expected: PASS — 3 tests green.

- [ ] **Step 6: Run full frontend type-check**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: clean.

- [ ] **Step 7: Run full frontend test suite (regression)**

Run: `cd frontend && pnpm vitest run`
Expected: existing tests stay green. The `livePersistedPillEquivalence`
test is the most likely to surface a missed update — read its assertions
if it fails and add `result_content: null` to any test fixtures it
constructs.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/chat/ToolCallPills.tsx frontend/src/features/chat/MessageList.tsx frontend/src/features/chat/__tests__/ToolCallPills.test.tsx
git commit -m "Render Request/Response sections in tool-call pill popover"
```

---

### Task 6: Frontend production build verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full Vite build**

Per CLAUDE.md, `tsc --noEmit` is not enough — `pnpm run build` runs
`tsc -b` which has stricter project-references checks.

Run: `cd frontend && pnpm run build`
Expected: build completes; emits the production bundle without TS errors.

- [ ] **Step 2: No commit**

This is a verification step.

---

## Part B — Streamable HTTP

### Task 7: Send `Accept: application/json, text/event-stream` on every MCP request

**Files:**
- Modify: `backend/modules/tools/_mcp_executor.py` (call_tool + discover_tools header blocks)
- Test: `tests/test_mcp_executor.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_mcp_executor.py` inside `class TestMcpExecutor`:

```python
    @pytest.mark.asyncio
    async def test_call_tool_sends_streamable_accept_header(self, executor):
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {
            "jsonrpc": "2.0", "id": 1,
            "result": {"content": [{"type": "text", "text": "ok"}]},
        }
        with patch("backend.modules.tools._mcp_executor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            await executor.call_tool(
                url="http://example.com/mcp",
                api_key=None,
                tool_name="ping",
                arguments={},
            )
            sent_headers = mock_client.post.call_args.kwargs["headers"]
            accept = sent_headers.get("Accept", "")
            assert "application/json" in accept
            assert "text/event-stream" in accept

    @pytest.mark.asyncio
    async def test_discover_tools_sends_streamable_accept_header(self, executor):
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {
            "jsonrpc": "2.0", "id": 1, "result": {"tools": []},
        }
        with patch("backend.modules.tools._mcp_executor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post.return_value = mock_response
            mock_client_cls.return_value = mock_client

            await executor.discover_tools(url="http://example.com/mcp", api_key=None)
            sent_headers = mock_client.post.call_args.kwargs["headers"]
            accept = sent_headers.get("Accept", "")
            assert "application/json" in accept
            assert "text/event-stream" in accept
```

- [ ] **Step 2: Run the test, expect failure**

Run: `PYTHONPATH=. uv run pytest tests/test_mcp_executor.py -v -k "streamable_accept"`
Expected: FAIL — Accept header is currently absent.

- [ ] **Step 3: Update both header blocks in `_mcp_executor.py`**

In `call_tool` (line ~41), replace:

```python
headers: dict[str, str] = {"Content-Type": "application/json"}
```

with:

```python
headers: dict[str, str] = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}
```

Apply the same change in `discover_tools` (line ~99).

- [ ] **Step 4: Run the new tests, expect pass; run the whole MCP test file**

Run: `PYTHONPATH=. uv run pytest tests/test_mcp_executor.py -v`
Expected: all tests PASS — existing JSON path is unaffected.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/tools/_mcp_executor.py tests/test_mcp_executor.py
git commit -m "Send Accept: application/json, text/event-stream on MCP requests"
```

---

### Task 8: Refactor `call_tool` to dispatch on response Content-Type (SSE branch)

**Files:**
- Modify: `backend/modules/tools/_mcp_executor.py` (call_tool body + new helper)
- Test: `tests/test_mcp_executor.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mcp_executor.py` inside `class TestMcpExecutor`:

```python
    @pytest.mark.asyncio
    async def test_call_tool_handles_sse_response(self, executor):
        """Server returns Content-Type: text/event-stream — parse the data: line."""
        sse_lines = [
            "data: {\"jsonrpc\":\"2.0\",\"id\":1,\"result\":{\"content\":[{\"type\":\"text\",\"text\":\"sse-result\"}]}}",
            "",
        ]

        class _FakeStreamResp:
            def __init__(self):
                self.headers = {"content-type": "text/event-stream; charset=utf-8"}
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def aiter_lines(self):
                for line in sse_lines:
                    yield line

        with patch("backend.modules.tools._mcp_executor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.stream = lambda *a, **kw: _FakeStreamResp()
            mock_client_cls.return_value = mock_client

            result = await executor.call_tool(
                url="http://fastmcp.example/mcp",
                api_key=None,
                tool_name="ping",
                arguments={},
            )
            parsed = json.loads(result)
            assert parsed["stdout"] == "sse-result"
            assert parsed["error"] is None

    @pytest.mark.asyncio
    async def test_call_tool_skips_sse_notifications(self, executor):
        """Notification arrives before the matching response — must skip the
        notification and return the response."""
        # Note: id assignment in McpExecutor is a process-global counter, so we
        # don't pin a specific value — we read it back from the request and
        # build the SSE reply to match. The simplest approach is to capture
        # the id off the outgoing request and respond with it.
        captured: dict = {}

        class _FakeStreamResp:
            def __init__(self):
                self.headers = {"content-type": "text/event-stream"}
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def aiter_lines(self):
                # 1) progress notification (no id) — must be ignored
                yield "data: {\"jsonrpc\":\"2.0\",\"method\":\"notifications/progress\",\"params\":{\"progress\":50}}"
                yield ""
                # 2) the matching response
                resp_id = captured["id"]
                yield (
                    f"data: {{\"jsonrpc\":\"2.0\",\"id\":{resp_id},"
                    "\"result\":{\"content\":[{\"type\":\"text\",\"text\":\"final\"}]}}"
                )
                yield ""

        def _stream(method, url, json, headers):
            captured["id"] = json["id"]
            return _FakeStreamResp()

        with patch("backend.modules.tools._mcp_executor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.stream = _stream
            mock_client_cls.return_value = mock_client

            result = await executor.call_tool(
                url="http://fastmcp.example/mcp", api_key=None,
                tool_name="ping", arguments={},
            )
            parsed = json.loads(result)
            assert parsed["stdout"] == "final"
            assert parsed["error"] is None

    @pytest.mark.asyncio
    async def test_call_tool_sse_closed_without_response(self, executor):
        """Stream ends without ever producing a matching JSON-RPC reply."""
        class _FakeStreamResp:
            def __init__(self):
                self.headers = {"content-type": "text/event-stream"}
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def aiter_lines(self):
                yield "data: {\"jsonrpc\":\"2.0\",\"method\":\"notifications/progress\",\"params\":{\"progress\":50}}"
                yield ""

        with patch("backend.modules.tools._mcp_executor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.stream = lambda *a, **kw: _FakeStreamResp()
            mock_client_cls.return_value = mock_client

            result = await executor.call_tool(
                url="http://fastmcp.example/mcp", api_key=None,
                tool_name="ping", arguments={},
            )
            parsed = json.loads(result)
            assert parsed["stdout"] == ""
            assert "error" in parsed and parsed["error"]
```

- [ ] **Step 2: Run the new tests, expect failure**

Run: `PYTHONPATH=. uv run pytest tests/test_mcp_executor.py -v -k "sse"`
Expected: FAIL — current code calls `resp.json()` and crashes.

- [ ] **Step 3: Refactor `call_tool` and add the SSE helper**

Replace the body of `call_tool` and add `_read_sse_response` at module
level. The full file body becomes:

```python
"""MCP JSON-RPC client for backend-executed tool calls (admin + user-remote gateways)."""

from __future__ import annotations

import inspect
import json
import logging

import httpx

_log = logging.getLogger(__name__)

_MCP_HTTP_TIMEOUT_S = 30
_REQUEST_ID_COUNTER = 0


def _next_request_id() -> int:
    global _REQUEST_ID_COUNTER
    _REQUEST_ID_COUNTER += 1
    return _REQUEST_ID_COUNTER


def _content_type(resp: httpx.Response) -> str:
    raw = resp.headers.get("content-type", "")
    return raw.split(";", 1)[0].strip().lower()


async def _read_sse_response(resp: httpx.Response, expected_id: int) -> dict:
    """Read an SSE stream until a JSON-RPC payload with `expected_id` arrives.

    Notifications (no `id`) are silently skipped, as are unrelated `id`s.
    Raises `RuntimeError` if the stream closes without a match.
    """
    async for line in resp.aiter_lines():
        if not line.startswith("data:"):
            continue
        data = line[5:].lstrip()
        if not data:
            continue
        try:
            obj = json.loads(data)
        except json.JSONDecodeError:
            _log.warning("MCP SSE: malformed data line: %r", data[:120])
            continue
        if obj.get("id") == expected_id:
            return obj
    raise RuntimeError("SSE stream closed without a matching JSON-RPC response")


class McpExecutor:
    """Calls MCP gateway tools via HTTP JSON-RPC.

    Stateless — one instance can be shared across connections.
    """

    async def call_tool(
        self,
        *,
        url: str,
        api_key: str | None,
        tool_name: str,
        arguments: dict,
    ) -> str:
        """Call a tool on a gateway and return JSON string {"stdout": ..., "error": ...}.

        Never raises. All failure modes produce an error in the returned JSON.
        Speaks the MCP Streamable HTTP transport: advertises support for both
        application/json and text/event-stream, and handles whichever the
        server picks.
        """
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        request_id = _next_request_id()
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }

        try:
            async with httpx.AsyncClient(timeout=_MCP_HTTP_TIMEOUT_S) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    ctype = _content_type(resp)

                    if ctype == "application/json":
                        body_bytes = await resp.aread()
                        _raw = json.loads(body_bytes)
                        body = (await _raw) if inspect.isawaitable(_raw) else _raw

                    elif ctype == "text/event-stream":
                        body = await _read_sse_response(resp, expected_id=request_id)

                    else:
                        _log.warning("MCP unexpected content-type from %s: %r", url, ctype)
                        return json.dumps({
                            "stdout": "",
                            "error": f"MCP gateway returned unexpected content-type: {ctype!r}",
                        })

            if "error" in body:
                err = body["error"]
                msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                _log.warning("MCP JSON-RPC error from %s: %s", url, msg)
                return json.dumps({"stdout": "", "error": f"MCP error: {msg}"})

            result = body.get("result", {})
            if result.get("isError"):
                content_parts = result.get("content", [])
                text = "\n".join(p.get("text", "") for p in content_parts if p.get("type") == "text")
                return json.dumps({"stdout": "", "error": text or "Tool returned an error"})

            content_parts = result.get("content", [])
            text = "\n".join(p.get("text", "") for p in content_parts if p.get("type") == "text")
            return json.dumps({"stdout": text, "error": None})

        except httpx.TimeoutException:
            _log.warning("MCP call timed out: %s tool=%s", url, tool_name)
            return json.dumps({"stdout": "", "error": f"MCP gateway timeout after {_MCP_HTTP_TIMEOUT_S}s"})
        except Exception as exc:
            _log.warning("MCP call failed: %s tool=%s error=%s", url, tool_name, exc)
            return json.dumps({"stdout": "", "error": f"MCP gateway unreachable: {exc}"})
```

The `discover_tools` method is rewritten in Task 9 — leave the existing
implementation alone for this commit.

- [ ] **Step 4: Re-bind the existing JSON tests to the new mock surface**

The existing `test_successful_call`, `test_call_with_auth`,
`test_jsonrpc_error_returns_error` tests in `tests/test_mcp_executor.py`
currently mock `mock_client.post.return_value`. With the new code, the
JSON path goes through `client.stream(...)` instead. Update those three
tests to use the same `_FakeStreamResp` pattern as the new SSE tests,
but with `content-type: application/json` and an `aread()` that returns
the JSON body bytes:

```python
class _FakeJsonResp:
    def __init__(self, body: dict):
        self.headers = {"content-type": "application/json"}
        self._body = json.dumps(body).encode("utf-8")
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def aread(self): return self._body
```

Each existing JSON test then does:

```python
with patch("backend.modules.tools._mcp_executor.httpx.AsyncClient") as mock_client_cls:
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.stream = lambda *a, **kw: _FakeJsonResp({...the body...})
    mock_client_cls.return_value = mock_client
    # ...
```

The `test_call_with_auth` test that previously read
`mock_client.post.call_args` needs to capture from `client.stream` —
adapt the same `_stream` capture pattern shown in
`test_call_tool_skips_sse_notifications` if call args matter, or simply
inspect headers via a stash dict captured by the stream lambda.

The `test_timeout_returns_error` test still works — it raises from the
client constructor / stream entry, which goes through the same
`except httpx.TimeoutException` path.

Also: the existing `test_call_tool_sends_streamable_accept_header` from
Task 7 needs the same JSON-stream re-bind; copy the `_FakeJsonResp`
shape into that test as well so it exercises the new dispatch path.

- [ ] **Step 5: Run the whole executor suite, expect pass**

Run: `PYTHONPATH=. uv run pytest tests/test_mcp_executor.py -v`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/tools/_mcp_executor.py tests/test_mcp_executor.py
git commit -m "MCP executor call_tool: dispatch on Content-Type, parse SSE responses"
```

---

### Task 9: Apply the same pattern to `discover_tools`

**Files:**
- Modify: `backend/modules/tools/_mcp_executor.py` (`discover_tools` method)
- Test: `tests/test_mcp_executor.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_mcp_executor.py`:

```python
    @pytest.mark.asyncio
    async def test_discover_tools_handles_sse_response(self, executor):
        """tools/list over text/event-stream — same dispatch logic as call_tool."""
        captured: dict = {}

        class _FakeStreamResp:
            def __init__(self):
                self.headers = {"content-type": "text/event-stream"}
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def aiter_lines(self):
                resp_id = captured["id"]
                yield (
                    f"data: {{\"jsonrpc\":\"2.0\",\"id\":{resp_id},"
                    "\"result\":{\"tools\":[{\"name\":\"ping\",\"description\":\"\",\"inputSchema\":{}}]}}"
                )
                yield ""

        def _stream(method, url, json, headers):
            captured["id"] = json["id"]
            return _FakeStreamResp()

        with patch("backend.modules.tools._mcp_executor.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.stream = _stream
            mock_client_cls.return_value = mock_client

            tools = await executor.discover_tools(url="http://fastmcp.example/mcp", api_key=None)
            assert isinstance(tools, list) and len(tools) == 1
            assert tools[0]["name"] == "ping"
```

- [ ] **Step 2: Run the test, expect failure**

Run: `PYTHONPATH=. uv run pytest tests/test_mcp_executor.py -v -k "discover_tools_handles_sse"`
Expected: FAIL.

- [ ] **Step 3: Rewrite `discover_tools` in `_mcp_executor.py`**

Replace the existing method:

```python
    async def discover_tools(
        self,
        *,
        url: str,
        api_key: str | None,
        timeout: float = 10.0,
    ) -> list[dict]:
        """Call tools/list on a gateway. Returns list of tool dicts or empty on failure.

        Does NOT raise — returns empty list on any error.
        Speaks Streamable HTTP just like call_tool.
        """
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        request_id = _next_request_id()
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/list",
        }

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    ctype = _content_type(resp)

                    if ctype == "application/json":
                        body_bytes = await resp.aread()
                        _raw = json.loads(body_bytes)
                        body = (await _raw) if inspect.isawaitable(_raw) else _raw

                    elif ctype == "text/event-stream":
                        body = await _read_sse_response(resp, expected_id=request_id)

                    else:
                        _log.warning("MCP discover unexpected content-type from %s: %r", url, ctype)
                        return []

            if "error" in body:
                _log.warning("MCP tools/list error from %s: %s", url, body["error"])
                return []

            return body.get("result", {}).get("tools", [])

        except Exception as exc:
            _log.warning("MCP tools/list failed for %s: %s", url, exc)
            return []
```

- [ ] **Step 4: Re-bind the existing discover_tools tests (if any) to the stream surface**

The Accept-header test added in Task 7
(`test_discover_tools_sends_streamable_accept_header`) currently mocks
`mock_client.post`. Re-bind it to use `_FakeJsonResp` via
`mock_client.stream` (analogous to Task 8 step 4). If `tests/test_mcp_executor.py`
has further `discover_tools` tests, apply the same change.

- [ ] **Step 5: Run the whole executor suite**

Run: `PYTHONPATH=. uv run pytest tests/test_mcp_executor.py -v`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/modules/tools/_mcp_executor.py tests/test_mcp_executor.py
git commit -m "MCP executor discover_tools: dispatch on Content-Type, parse SSE responses"
```

---

## Final verification (manual)

These steps are run by Chris on the dev stack — they are not committed.
The plan ends here; the subagent does NOT merge or push (per the
`subagent_no_merge` rule).

- [ ] **Step 1: Frontend production build sanity check**

Run: `cd frontend && pnpm run build`
Expected: clean build.

- [ ] **Step 2: Backend test suite (host-safe subset)**

The MongoDB-using test files must be excluded on host (per
`db_tests_on_host`). Adjust the ignore list to whatever the project
already uses; one shape that works:

```bash
PYTHONPATH=. uv run pytest \
    --ignore=tests/integration \
    --ignore=tests/modules/persona/test_repository.py \
    --ignore=tests/modules/user/test_repository.py \
    --ignore=tests/modules/chat/test_repository.py \
    -q
```

Expected: all green.

- [ ] **Step 3: Manual verification per spec §8**

Run through the six steps in
`devdocs/specs/2026-05-10-mcp-pills-result-and-streamable-http-design.md`
§8 against a live dev stack: pills happy path, error path, legacy data,
JSON-only server, FastMCP server, Accept header always present.

- [ ] **Step 4: STOP**

Subagent does NOT merge to master, does NOT push, does NOT switch
branches. Report back to Chris with: list of commits on
`feat/mcp-polish`, frontend build result, backend test result, and
verification status (or what could not be verified on host vs needs
real-stack manual run).
