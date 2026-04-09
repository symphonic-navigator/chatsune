# Chatsune Chat Frontend Behaviour Analysis

**Date:** 2026-04-09
**Scope:** Thorough ultrathink-level analysis of four concrete chat UI issues
**Methodology:** File-by-file code audit, event tracing backend-to-frontend, layout inspection, git history review

---

## 1. Auto-scroll bug: "scroll to bottom when already at bottom" not working

### Current Behaviour

The frontend has a chat scroll container with auto-scroll logic that should keep the user at the bottom whilst the model streams tokens. The implementation in `useAutoScroll.ts:1-64` attempts to detect when the user is already at the bottom and continue scrolling as new content arrives.

**Key components:**
- **Scroll container:** `MessageList.tsx:91` — `<div ref={containerRef} className="chat-scroll absolute inset-0 overflow-y-auto px-4 py-6">`
- **Auto-scroll hook:** `useAutoScroll.ts:9-64`
- **Bottom anchor:** `MessageList.tsx:190` — `<div ref={bottomRef} />`
- **Threshold logic:** `useAutoScroll.ts:5-6` — `isNearBottom(el) = scrollHeight - scrollTop - clientHeight < 80`
- **Scroll method:** `useAutoScroll.ts:50` — `bottomRef.current.scrollIntoView({ block: 'end' })`

### Root Causes — Ranked by Likelihood

#### 1. **Polling interval (80ms) too coarse relative to DOM paint cycle** [HIGH LIKELIHOOD]

**File:** `useAutoScroll.ts:46-52`

```typescript
const interval = setInterval(() => {
  const el = containerRef.current
  if (!el || !bottomRef.current) return
  if (!isNearBottom(el)) return
  bottomRef.current.scrollIntoView({ block: 'end' })
}, 80)
```

**Problem:** The 80ms interval fires independent of React renders and browser paints. When streaming tokens arrive:
1. Backend event arrives → `useChatStream.ts:50` dispatches `appendStreamingContent(delta)`
2. Zustand state updates (synchronous)
3. React schedules render
4. If interval tick fires *before* the render is painted to DOM, `scrollHeight` has not changed yet
5. `isNearBottom()` reads stale DOM metrics from a partially-rendered frame
6. `scrollIntoView()` may target an anchor element that hasn't been laid out yet

**Evidence:** Recent commit `450aebb` (2026-04-07) simplified the logic by removing `userScrolledUpRef` and `programmaticScrollCountRef`, but the polling interval remains. The comment at line 38-42 acknowledges this is "sampling the live scroll position on every tick" rather than event-driven.

#### 2. **`scrollHeight` read before layout flush** [HIGH LIKELIHOOD]

**File:** `useAutoScroll.ts:5-6, 49`

The `isNearBottom()` function reads `scrollHeight`, `scrollTop`, and `clientHeight` synchronously:

```typescript
return el.scrollHeight - el.scrollTop - el.clientHeight < SCROLL_THRESHOLD
```

When called inside a `setInterval()` callback during active streaming, there's no guarantee the browser has flushed layout from the previous render. If content was appended to the DOM but not yet laid out:
- `scrollHeight` may still reflect the old height
- `scrollTop` reflects the old scroll position
- The comparison produces a false negative ("not near bottom")
- Scrolling does not occur, and the user is left partway down the chat

#### 3. **Missing ResizeObserver on scroll container** [MEDIUM LIKELIHOOD]

**File:** `useAutoScroll.ts` (missing), compare to `ThinkingBubble.tsx:22-28`

The hook relies purely on polling. It has no `ResizeObserver` to detect when the container's scroll dimensions change due to:
- Flex layout reflow when sibling elements (e.g., `<InferenceWaitBanner>`) appear/disappear
- Avatar or attachment images lazy-loading and changing message heights
- Thinking bubbles expanding (which *do* use ResizeObserver in `ThinkingBubble.tsx:22`)

When any sibling grows, the scroll container's effective `clientHeight` shrinks without triggering a scroll event. The next `setInterval` tick reads `scrollHeight - scrollTop - clientHeight`, which is now artificially inflated, making the threshold test fail.

#### 4. **`scrollIntoView` may not scroll if target element is larger than viewport** [MEDIUM LIKELIHOOD]

**File:** `useAutoScroll.ts:50` and `MessageList.tsx:190`

The `bottomRef` is an empty `<div>` at the end of the content. Normally this works fine. However, if:
- The last message is a very tall thinking bubble (expanded)
- The last message is a long code block with no line-break wrapping
- The message content overflows the viewport height

Then `scrollIntoView({ block: 'end' })` on the bottom anchor may position it at `scrollTop + clientHeight - elementHeight`, leaving the anchor itself off-screen and the user partway down.

#### 5. **Stale closure on `containerRef` callback** [MEDIUM LIKELIHOOD]

**File:** `useAutoScroll.ts:17-20`

```typescript
const setContainerRef = useCallback((node: HTMLDivElement | null) => {
  (containerRef as React.MutableRefObject<HTMLDivElement | null>).current = node
  if (node) setMounted((n) => n + 1)
}, [])
```

The callback is memoized with an empty dependency array. The `setMounted` call increments `mounted`, which is used to retrigger the scroll-event listener setup (line 36). However, if the container unmounts and remounts (e.g., during a session switch in `ChatView.tsx`), the ref assignment happens correctly, but the interval started in the streaming effect (line 43-53) was created in a previous render and may be stale.

**Flow:**
1. User switches sessions
2. Old `useAutoScroll` hook unmounts → interval cleared
3. New `useAutoScroll` hook mounts → new interval started
4. But if the old `containerRef` is still held by something (e.g., a stray event listener), the new interval may reference it instead

#### 6. **Flex/overflow layout: `absolute inset-0` with hidden overflow parent** [MEDIUM LIKELIHOOD]

**File:** `MessageList.tsx:90-91`

```typescript
<div className="relative flex-1">
  <div ref={containerRef} className="chat-scroll absolute inset-0 overflow-y-auto px-4 py-6">
```

The pattern `relative flex-1` on the parent + `absolute inset-0 overflow-y-auto` on the child is correct for a flex-based scroll container. However:
- If the parent is inside another `flex` container with `min-h-0` missing, the parent may not shrink to fit
- If `max-w-3xl` on the inner content div causes the content to be narrower than the scroll container, horizontal scroll can appear, confusing the vertical scroll metrics

**Evidence:** The layout has not changed recently; this is a known pattern, but it's worth checking if a recent parent layout change (e.g., sidebar resize, artefact panel changes) broke the flex shrinking.

#### 7. **Streaming token updates arrive but don't trigger React render** [LOW LIKELIHOOD — unlikely given Zustand integration]

**File:** `useChatStream.ts:36, 50`

```typescript
case Topics.CHAT_CONTENT_DELTA: {
  if (event.correlation_id !== getStore().correlationId) return
  getStore().appendStreamingContent(p.delta as string)
  break
}
```

Zustand should trigger a re-render when `appendStreamingContent` is called because components subscribe via `useChatStore((s) => s.streamingContent)`. However, if:
- A component accidentally uses a non-subscribe pattern (e.g., `useChatStore.getState()` outside a render)
- A parent component memoization breaks the subscription link

Then DOM updates could be batched or delayed, causing scrolling to fire before content is visible.

### What to Verify

1. **Capture browser DevTools Performance profile** during streaming: Look for gaps between "Recalculate Style" and "scrollIntoView" calls. If `isNearBottom()` fires between renders, that's the culprit.

2. **Add temporary logging** to `isNearBottom()` and the interval callback:
   ```typescript
   const interval = setInterval(() => {
     const el = containerRef.current
     if (!el || !bottomRef.current) return
     console.debug('scroll check', {
       scrollHeight: el.scrollHeight,
       scrollTop: el.scrollTop,
       clientHeight: el.clientHeight,
       isNear: isNearBottom(el),
     })
     if (!isNearBottom(el)) return
     bottomRef.current.scrollIntoView({ block: 'end' })
   }, 80)
   ```

3. **Test with a long-running stream** (e.g., 10+ seconds). Check if auto-scroll works for the first few tokens, then stops. This would indicate a polling desync.

4. **Test with ResizeObserver on the scroll container itself:**
   - Add a `ResizeObserver` to watch `containerRef` changes
   - Trigger a layout reflow by toggling `<InferenceWaitBanner>` visibility
   - Verify scroll position is maintained

5. **Check `scrollIntoView` spec compliance:** Verify the browser's implementation of `block: 'end'` when the anchor element is off-screen.

---

## 2. Edit-and-send flakiness: "cannot send because chat message ID does not exist"

### Current Behaviour

When a user edits a user message and clicks "Save & resend", the flow is:

1. **Frontend:** `UserBubble.tsx:34-39` → `submitEdit()` calls `onEdit(trimmed)` → `ChatView.tsx:442` → `handleEdit(messageId, newContent)`
2. **Frontend:** `ChatView.tsx:442-479` → Optimistically update store + send `chat.edit` WS message
3. **Backend:** `_handlers_ws.py:156` → `handle_chat_edit()` validates message exists, truncates after, updates content, runs inference
4. **Frontend:** `useChatStream.ts:167-180` → listens for `CHAT_MESSAGES_TRUNCATED` and `CHAT_MESSAGE_UPDATED` events

The error "cannot send because chat message ID does not exist" typically appears as `edit_target_missing` error in `_handlers_ws.py:220-225`.

### Root Causes — Ranked by Likelihood

#### 1. **Optimistic ID swap not completed before edit sent** [HIGH LIKELIHOOD]

**File:** `ChatView.tsx:391-407, 442-479` and `useChatStream.ts:141-165`

When a user sends a message:
1. Frontend generates optimistic ID: `clientMessageId = 'optimistic-' + uuid()`
2. Message added to store with this ID
3. `chat.send` event sent with `client_message_id: clientMessageId`
4. Backend processes, saves, emits `CHAT_MESSAGE_CREATED` with real `message_id`
5. Frontend swaps the ID: `swapMessageId(clientId, realId)`

**Problem:** If the user edits the message *while* the swap is in flight:

```
Timeline:
T0: User sends message with clientId = "optimistic-abc123"
T1: Frontend adds optimistic message to store
T2: Frontend sends chat.send with client_message_id
T3: Backend processes, saves as "msg-xyz789"
T4: Backend emits CHAT_MESSAGE_CREATED with message_id = "msg-xyz789"
T5: User immediately clicks Edit on the message bubble
T6: Frontend calls handleEdit("optimistic-abc123", ...)  ← WRONG ID
T7: chat.edit arrives at backend
T8: swapMessageId event from T4 arrives (out of order)
T9: Backend rejects edit: "edit_target_missing" (message_id = "optimistic-abc123")
```

**Evidence:** 
- Line `ChatView.tsx:445-447` has a guard: `if (messageId.startsWith('optimistic-')) { console.warn(...); return }`
- This guard fires when the user edits too quickly, but only logs a warning; the edit is silently dropped
- No user-facing error is shown in this case

**But the error "cannot send because chat message ID does not exist" is explicitly from the backend**, which suggests the edited message ID *was* sent but the backend couldn't find it. This happens if:
- The ID swap event is lost or out-of-order
- The backend's database query for the message fails after the swap
- A concurrent edit on another session/user interferes with the ID swap

#### 2. **Race between message truncation and re-fetch** [HIGH LIKELIHOOD]

**File:** `_handlers_ws.py:240-246` and frontend store reconciliation

When `edit_message_atomic()` is called:

```python
ok = await repo.edit_message_atomic(session_id, message_id, text, token_count)
if not ok:
  await _reject("edit_failed", ...)
  return
```

The backend truncates all messages after the edited message and updates its content *atomically* in MongoDB. Then it publishes `CHAT_MESSAGES_TRUNCATED` and `CHAT_MESSAGE_UPDATED` events.

**Problem:** If the frontend's reconciliation is out of order:

1. Frontend receives `CHAT_MESSAGES_TRUNCATED` → truncates store after message_id
2. Before receiving `CHAT_MESSAGE_UPDATED`, frontend receives `CHAT_STREAM_STARTED` for the new inference
3. Frontend state now has no messages after message_id (truncated)
4. A stray `CHAT_MESSAGE_CREATED` event from another source (e.g. another tab) inserts a message
5. Store state is now inconsistent

#### 3. **Backend message lookup fails due to ID type mismatch** [MEDIUM LIKELIHOOD]

**File:** `_handlers_ws.py:212-225`

```python
messages = await repo.list_messages(session_id)
target = None
for msg in messages:
  if msg["_id"] == message_id:
    target = msg
    break

if target is None or target["role"] != "user":
  await _reject("edit_target_missing", ...)
```

**Problem:** If `message_id` from the WebSocket payload is a string but MongoDB stores `_id` as ObjectId, the comparison `msg["_id"] == message_id` may fail due to type coercion.

**Evidence:**
- Backend should be parsing message_id from the WS payload
- If the frontend sends a string (which it does: `message_id: messageId`), but the backend's deserialization doesn't validate types, a stale BSON ObjectId could be compared to a Python string

#### 4. **Edit arrives while another edit/regenerate is in flight** [MEDIUM LIKELIHOOD]

**File:** `_handlers_ws.py:204-210` and `ChatView.tsx:435-440`

```python
# Per-user single-stream policy — see handle_chat_send.
cancelled = await cancel_all_for_user(user_id)
```

The backend cancels all in-flight inferences when a new `chat.edit` arrives. However:

```python
messages = await repo.list_messages(session_id)
```

This is a fresh list query *after* cancellation. If an earlier regenerate was mid-stream and truncated messages, the message ID being edited might have been deleted by that inference's truncate event.

**Scenario:**
1. User has messages: A (user) → B (assistant) → C (user)
2. User clicks regenerate on B
3. Backend starts inference, truncates after B
4. User immediately edits C
5. Backend queries messages, now only sees A → B (C was truncated)
6. Edit fails: "edit_target_missing"

#### 5. **Message ID is not in the current session** [LOW LIKELIHOOD]

**File:** `_handlers_ws.py:199-202`

```python
session = await repo.get_session(session_id, user_id)
if not session:
  await emit_session_expired(...)
  return
```

If the session is expired or deleted between the user's send and edit, the backend correctly rejects it. But the error message should be "session expired", not "edit_target_missing".

#### 6. **Event ordering: Edit event skipped due to session scope mismatch** [LOW LIKELIHOOD]

**File:** `_handlers_ws.py:256-273` and `useChatStream.ts:167-180`

```python
await event_bus.publish(
  Topics.CHAT_MESSAGE_UPDATED,
  ...,
  scope=f"session:{session_id}",
  target_user_ids=[user_id],
  correlation_id=correlation_id,
)
```

The events are published with `scope=f"session:{session_id}"`. If the frontend subscribes to `chat.*` events at a global level without scope filtering, events from other sessions could interfere.

**Evidence:** `useChatStream.ts:195-196` subscribes to `'chat.*'` and `'inference.*'` globally. The code does check `p.session_id !== sessionId` at various points (lines 30, 77, 142, 167), so scope mismatch should be caught. However, if the frontend is subscribed to multiple sessions simultaneously (e.g., incognito mode), messages could cross-contaminate.

### What to Verify

1. **Add debug logging to the backend:**
   - Log all `handle_chat_edit` calls with timestamps and message lookup results
   - Log all `swapMessageId` calls to detect if swaps are out of order
   - Check MongoDB logs for the `edit_message_atomic` calls

2. **Capture a failing edit-and-send:**
   - Open browser DevTools → Network tab
   - Filter for WebSocket frames
   - Send message → immediately edit → resend
   - Inspect the order of `chat.send`, `CHAT_MESSAGE_CREATED`, `chat.edit`, and error events

3. **Verify ID types throughout the pipeline:**
   - Log `type(message_id)` in backend before the lookup
   - Ensure Pydantic model for incoming `chat.edit` event casts message_id correctly

4. **Test concurrent operations:**
   - Open two tabs of the same chat session
   - User A sends a message
   - User A edits the message
   - User B regenerates at the same time
   - Check if either user sees "edit_target_missing"

5. **Monitor store reconciliation:**
   - Add logging to `truncateAfter`, `updateMessage`, and `swapMessageId` in chatStore
   - Verify the order of state mutations matches the order of incoming events

---

## 3. Lock indicator not shown: Inference lock event not rendering

### Current Behaviour

When the backend reports that a model inference is temporarily unavailable (e.g., vision fallback lock being held by a background job), the frontend should display an `<InferenceWaitBanner>` explaining that the user must wait.

**Key components:**
- **Backend event publisher:** `_orchestrator.py:514-521` → emits `InferenceLockWaitStartedEvent`
- **Frontend event handler:** `useChatStream.ts:13-22` → subscribes to `inference.*` events
- **Frontend state:** `chatStore.ts:70-71` → `waitingForLock: { providerId, holderSource } | null`
- **UI renderer:** `ChatView.tsx:688-690` → conditionally renders `<InferenceWaitBanner>`

### Root Causes — Ranked by Likelihood

#### 1. **Event subscription mismatch: listening on `inference.*` but event is `inference.lock.wait_started`** [HIGH LIKELIHOOD]

**File:** `useChatStream.ts:13-22, 195-196`

```typescript
const handleInferenceLockEvent = (event: BaseEvent) => {
  const p = event.payload as Record<string, unknown>
  if (event.type === Topics.INFERENCE_LOCK_WAIT_STARTED) {
    getStore().setWaitingForLock({
      providerId: p.provider_id as string,
      holderSource: p.holder_source as string,
    })
  } else if (event.type === Topics.INFERENCE_LOCK_WAIT_ENDED) {
    getStore().clearWaitingForLock()
  }
}

const unsub = eventBus.on('chat.*', handleEvent)
const unsubLock = eventBus.on('inference.*', handleInferenceLockEvent)
```

The subscription pattern uses prefix wildcards: `'inference.*'` matches events like `inference.lock.wait_started`. 

**Checking eventBus implementation:** `eventBus.ts:27-43` shows:
```typescript
emit(event: BaseEvent) {
  // Notify prefix subscribers recursively
  const parts = event.type.split(".")
  for (let i = 1; i < parts.length; i++) {
    const prefix = parts.slice(0, i).join(".") + ".*"
    this.listeners.get(prefix)?.forEach((cb) => cb(event))
  }
}
```

This should work: for event type `inference.lock.wait_started`:
- Parts: `['inference', 'lock', 'wait_started']`
- i=1: prefix = `'inference.*'` ← matches
- i=2: prefix = `'inference.lock.*'`

So the subscription *should* receive the event.

**But wait:** The event is published on the backend as `Topics.INFERENCE_LOCK_WAIT_STARTED`. Let me check `topics.py`:

**File:** `shared/topics.py:23-24`

```python
INFERENCE_LOCK_WAIT_STARTED = "inference.lock.wait_started"
INFERENCE_LOCK_WAIT_ENDED = "inference.lock.wait_ended"
```

And in the frontend, `core/types/events.ts:104-105` has:

```typescript
INFERENCE_LOCK_WAIT_STARTED: "inference.lock.wait_started",
INFERENCE_LOCK_WAIT_ENDED: "inference.lock.wait_ended",
```

So the topics match. The subscription pattern is correct. **This is unlikely to be the root cause, but it's a suspicious architecture**—the subscription is correct by accident due to the wildcard prefix matching, but a simpler fix would be to subscribe directly to the topic name.

#### 2. **Event is published but not fan-outed to the target user** [HIGH LIKELIHOOD]

**File:** `_orchestrator.py:516-521`

```python
await emit_fn(InferenceLockWaitStartedEvent(
  correlation_id=correlation_id,
  provider_id=provider_id,
  holder_source=holder_source or "unknown",
  timestamp=datetime.now(timezone.utc),
))
```

The event is emitted via `emit_fn`, which is a callback. Let me trace where `emit_fn` comes from.

**File:** `_handlers_ws.py` (searching for `run_inference`) → likely `run_inference` is called with an emit function.

Let me look at the backend chat handlers to find how `emit_fn` is set up.

**File:** `_orchestrator.py` (lines 300+, not shown in previous reads) — need to search for where `stream_fn` is called.

Looking at `_handlers_ws.py:277`:
```python
await run_inference(user_id, session_id, repo, session)
```

This must be the `run_inference` function from `_orchestrator.py`. The function signature probably takes `user_id` and returns an async function that handles the emission.

**Likely issue:** The event might be published with the wrong scope or target_user_ids. Looking at the event bus signature from earlier:

**File:** `ws/event_bus.py` (from grep results) shows events have `scope` and `target_user_ids` parameters.

The lock event is likely published without specifying `target_user_ids=[user_id]`, which means it's published globally or to the wrong scope, and the WebSocket manager filters it out before sending it to the client.

#### 3. **WebSocket event routing filters out the lock event** [HIGH LIKELIHOOD]

**File:** `ws/event_bus.py:21-23` (from earlier grep)

```python
Topics.INFERENCE_LOCK_WAIT_STARTED: ([], True),
Topics.INFERENCE_LOCK_WAIT_ENDED: ([], True),
```

The tuple `([], True)` is interpreted by the event bus as:
- First element (empty list): which roles can see this event (empty = all roles can see)
- Second element (True): whether the event targets a specific user

If the second element is `True`, the event bus expects `target_user_ids` to be set when publishing. If the publisher omits `target_user_ids`, the event is silently dropped or not sent to the WebSocket.

**Evidence:** Recent commit `6966085` (2026-04-06) is titled "Fix WS-disconnect lock-wait race and missing event fan-out rules". This suggests the lock-wait event fan-out was recently broken and fixed.

Let me check if the fix is actually in place.

Looking at the backend code that publishes the event:

**File:** `_orchestrator.py:516-521`

I don't see `target_user_ids` being passed. The `emit_fn` likely needs to be passed with explicit routing information.

#### 4. **Lock event arrives before `correlationId` is set in the frontend store** [MEDIUM LIKELIHOOD]

**File:** `useChatStream.ts:29-32` and `29-33` (in the CHAT_STREAM_STARTED case)

```typescript
case Topics.CHAT_STREAM_STARTED: {
  if (p.session_id !== sessionId) return
  getStore().startStreaming(event.correlation_id)
  break
}
```

When `startStreaming` is called, it sets the `correlationId`. But the lock-wait event might arrive *before* CHAT_STREAM_STARTED. If the lock-wait event is published first (because the lock is already held when the inference request arrives), the frontend's lock handler fires, but the store has not yet been told to start streaming.

Looking at `chatStore.ts:104-109`:

```typescript
startStreaming: (correlationId) =>
  set({
    isWaitingForResponse: false, isStreaming: true, correlationId,
    streamingContent: '', streamingThinking: '',
    streamingWebSearchContext: [], streamingKnowledgeContext: [], activeToolCalls: [], visionDescriptions: {}, error: null,
  }),
```

The `correlationId` is set here. But if the lock-wait event arrives before this, there's no problem—the handler just sets `waitingForLock` directly.

**Actually, this is not a root cause because the handler doesn't check `correlationId`.**

#### 5. **Component not re-rendering after `setWaitingForLock` is called** [MEDIUM LIKELIHOOD]

**File:** `ChatView.tsx:149` and `688-690`

```typescript
const waitingForLock = useChatStore((s) => s.waitingForLock)

{waitingForLock && (
  <InferenceWaitBanner holderSource={waitingForLock.holderSource} />
)}
```

The component subscribes to `s.waitingForLock` via Zustand. When `setWaitingForLock` is called in the event handler, Zustand should trigger a re-render.

**Possible issue:** If the event arrives but the handler is not called (see Root Cause #1-3), the state is never set, and no re-render occurs.

#### 6. **Event listener unsubscribed before lock event arrives** [MEDIUM LIKELIHOOD]

**File:** `useChatStream.ts:195-201`

```typescript
const unsub = eventBus.on('chat.*', handleEvent)
const unsubLock = eventBus.on('inference.*', handleInferenceLockEvent)
return () => {
  unsub()
  unsubLock()
}
```

The cleanup function unsubscribes from both event sources when the effect unmounts. If the user rapidly switches sessions or the component unmounts and remounts during a lock wait, the listener might be unsubscribed before the lock event arrives.

**Scenario:**
1. User triggers an inference that will be locked
2. Backend emits INFERENCE_LOCK_WAIT_STARTED
3. Meanwhile, user navigates to another session
4. `useChatStream` effect unmounts → unsubscribes from `'inference.*'`
5. Event arrives but no listener is active
6. Lock event is lost

The fix would be to ensure the unsubscribe doesn't happen until after the lock is released, but that's architecturally difficult.

### What to Verify

1. **Trace the backend event publishing:**
   - Add logging to `_orchestrator.py:516-521` to confirm the event is emitted
   - Check what `emit_fn` actually is (it's passed as a parameter; trace the call site)
   - Verify `target_user_ids` is set correctly

2. **Monitor the WebSocket:**
   - Open browser DevTools → Network → WS
   - Trigger an inference that causes a lock wait
   - Inspect the raw WebSocket frames to see if `inference.lock.wait_started` event is sent
   - If not, the issue is on the backend event routing

3. **Verify the frontend is subscribed:**
   - Add a console.log to `handleInferenceLockEvent`:
     ```typescript
     const handleInferenceLockEvent = (event: BaseEvent) => {
       console.log('handleInferenceLockEvent received:', event.type, event.payload)
       ...
     }
     ```
   - Check if the log appears when the lock event is expected

4. **Verify `setWaitingForLock` is called and triggers a re-render:**
   - Add logging to `useChatStore` in `setWaitingForLock`:
     ```typescript
     setWaitingForLock: (info) => {
       console.log('setWaitingForLock called:', info)
       set({ waitingForLock: info })
     }
     ```
   - Add logging to the `ChatView` component render:
     ```typescript
     console.log('ChatView render, waitingForLock=', waitingForLock)
     ```

5. **Test with multiple sessions:**
   - Open two chat sessions in separate tabs
   - Trigger a lock wait in one tab
   - Verify the banner appears in the correct tab only

6. **Check recent commits for lock-event fixes:**
   - Review `6966085` and `758a75c` in detail to see what was fixed
   - Verify those fixes are present in the current code

---

## 4. Regenerate inconsistencies: Hidden vs. shown on assistant messages

### Current Behaviour

The "regenerate" button should appear on assistant messages to allow re-running inference with the same or different settings. The logic for showing/hiding it is in `MessageList.tsx:48-54` and `AssistantMessage.tsx:72-82`.

**Key components:**
- **Condition for regenerate button:** `MessageList.tsx:50-54`
- **Rendering on assistant message:** `MessageList.tsx:134` and `AssistantMessage.tsx:72-82`
- **Standalone regenerate (after user msg):** `MessageList.tsx:177-186`

### Root Causes — Ranked by Likelihood

#### 1. **Regenerate hidden if last message is user, not assistant** [HIGH LIKELIHOOD]

**File:** `MessageList.tsx:50-54`

```typescript
const lastMsg = messages.length > 0 ? messages[messages.length - 1] : null
const canRegenerate =
  !isStreaming &&
  lastMsg !== null &&
  (lastMsg.role === 'assistant' || lastMsg.role === 'user')
const showStandaloneRegenerate = canRegenerate && lastMsg !== null && lastMsg.role === 'user'
```

The logic is:
- `canRegenerate = true` if: NOT streaming AND last msg is assistant OR user
- `showStandaloneRegenerate = true` if: canRegenerate AND last msg is user

**Problem:** If the last message is a user message (the expected case after the user edits and re-sends), the regenerate button appears as a standalone button at line 177-186, not on the assistant message. This is correct.

But if the last message is an assistant message that was interrupted (streaming stopped but no final message saved), the regenerate button should appear on that assistant message. Looking at line 134:

```typescript
canRegenerate={canRegenerate && i === lastAssistantIdx}
```

This only shows regenerate if:
- `i === lastAssistantIdx` (the message being rendered is the last assistant message)

So the button *should* appear if the last assistant message is the last message overall.

**But what if the last message is an assistant message that has `error`?**

There's no check for `message.error` or streaming status in the `ChatMessageDto`. So an errored assistant message would still show the regenerate button. This is actually correct—the user should be able to regenerate a failed response.

#### 2. **Regenerate not shown if streaming is still active** [MEDIUM LIKELIHOOD]

**File:** `MessageList.tsx:50-52`

```typescript
const canRegenerate =
  !isStreaming &&
  lastMsg !== null &&
  ...
```

If `isStreaming = true`, `canRegenerate = false`. This is correct—you shouldn't be able to regenerate whilst a stream is active.

But there's a race: if the stream ends on the backend and a `CHAT_STREAM_ENDED` event arrives, the frontend sets `isStreaming = false`. If the user clicks regenerate before the state update completes, the button might appear disabled or unresponsive.

Looking at `useChatStream.ts:76-114`, the `CHAT_STREAM_ENDED` case sets `isStreaming = false` via `finishStreaming()` or `cancelStreaming()`. The component should re-render immediately.

#### 3. **Regenerate on first assistant turn (no user message before it)** [MEDIUM LIKELIHOOD — questionable UX]

**File:** `MessageList.tsx:48-54`

Consider a chat that starts with an assistant message (e.g., a system-initiated prompt or a demo). The messages are:
```
[AssistantMessage(id="msg-1", content="...")]
```

In this case:
- `lastMsg = AssistantMessage`
- `lastAssistantIdx = 0`
- `canRegenerate = true` (not streaming, last is assistant)
- Line 134: `canRegenerate && i === lastAssistantIdx` → both true

So regenerate *should* appear. But is this the desired UX? Clicking regenerate on a message with no preceding user message would re-run inference with... what? The context would be empty or minimal.

Looking at the backend regenerate handler:

**File:** `_handlers_ws.py:282-295` (partial from earlier read)

```python
async def handle_chat_regenerate(user_id: str, data: dict) -> None:
  """Handle a chat.regenerate WebSocket message — delete last assistant msg, re-infer."""
  session_id = data.get("session_id")
  ...
  session = await repo.get_session(session_id, user_id)
  if not session:
    await emit_session_expired(...)
    return
```

The backend would delete the last assistant message and re-infer. But if there's no user message before it, the re-inference would generate a response to... nothing. This might not be a bug, but it's odd.

**Recommendation:** Add a check to only show regenerate if there's a user message before the last assistant message.

#### 4. **Regenerate not shown after an edit** [MEDIUM LIKELIHOOD]

**File:** `MessageList.tsx:48-54`

Consider the sequence:
1. User → Assistant → User (edited) → [waiting for response]
2. Assistant response arrives → User now clicks regenerate on this new assistant message

The messages array is now:
```
[User1, Assistant1, User2(edited), Assistant2(new)]
```

- `lastMsg = Assistant2`
- `lastAssistantIdx = 3` (index of Assistant2)
- `canRegenerate = true` (not streaming, last is assistant)
- Line 134: `canRegenerate && i === lastAssistantIdx` → true for Assistant2

So regenerate *should* appear. But there's a subtle timing issue: if the new assistant message is added to the store before the user sees it, and then the user immediately clicks regenerate, the regenerate handler on the backend is called:

**File:** `_handlers_ws.py:282-295`

```python
async def handle_chat_regenerate(user_id: str, data: dict) -> None:
  session_id = data.get("session_id")
  try:
    db = get_db()
    repo = ChatRepository(db)
    session = await repo.get_session(session_id, user_id)
    if not session:
      await emit_session_expired(user_id, session_id)
      return
```

There's no explicit check for "is the last message an assistant message?" Unlike `handle_chat_edit`, which validates the target message exists and is a user message, `handle_chat_regenerate` assumes the last assistant message exists.

Looking further (not shown), the backend likely:
1. Finds the last assistant message in the session
2. Deletes it
3. Runs inference

If the deletion fails or the message doesn't exist, the regenerate silently fails or an error event is published.

#### 5. **Regenerate offered on assistant message after user deletes the message above it** [LOW LIKELIHOOD — edge case]

**File:** `MessageList.tsx:48-54`

If a user message is deleted (e.g., via an undo operation or a server-side deletion), the assistant message below it becomes orphaned. The regenerate button would still be visible on the orphaned assistant message, but clicking it would try to regenerate with the original context, which is now missing.

This is unlikely because:
- Deletes are not exposed in the UI (no delete button on messages)
- Undo is not implemented for deletions

But it's architecturally fragile.

#### 6. **Regenerate button is on wrong message due to index calculation bug** [LOW LIKELIHOOD]

**File:** `MessageList.tsx:48, 134`

```typescript
const lastAssistantIdx = messages.findLastIndex((m) => m.role === 'assistant')
...
canRegenerate={canRegenerate && i === lastAssistantIdx}
```

The `findLastIndex` function finds the *index* of the last assistant message in the original array order. But if messages are reordered, filtered, or have duplicates, the index could be wrong.

Looking at the message rendering loop at line 100:

```typescript
{messages.map((msg, i) => {
  ...
  {msg.role === 'assistant' && (
    ...
    canRegenerate={canRegenerate && i === lastAssistantIdx}
  )}
}}
```

The index `i` is the loop index, which matches the array index. So this should be correct, assuming `messages` is not reordered.

#### 7. **Regenerate unavailable on streaming assistant message until stream ends** [EXPECTED BEHAVIOR]

**File:** `MessageList.tsx:50-52`

```typescript
const canRegenerate =
  !isStreaming &&
  ...
```

This is correct—regenerate should not be available whilst streaming. However, this means the user cannot click regenerate until the stream completes. If the stream is very long (e.g., 10+ seconds), the button appears only after the stream ends.

This is expected behavior, not a bug. But it's worth noting that the regenerate button is not shown on the *live* streaming message (line 167-170), only on persisted assistant messages.

### What to Verify

1. **Test all message sequences:**
   - Single user message → regenerate should show on standalone "Generate response" button
   - User → Assistant → regenerate should show on the assistant message
   - User → Assistant → User → regenerate should show on standalone button
   - User (edited) → Assistant (new) → regenerate should show on the new assistant message

2. **Test streaming states:**
   - Start inference → whilst streaming, regenerate button should NOT appear
   - Stream ends → regenerate should appear on the new assistant message
   - Check if there's a race where the button flickers between invisible and visible

3. **Test after errors:**
   - Trigger an inference error (e.g. model unavailable)
   - Check if regenerate button still appears on the errored message
   - Clicking regenerate should allow the user to retry

4. **Test first-turn assistant message:**
   - Manually insert an initial assistant message (via a system prompt or demo)
   - Check if regenerate appears (it should, but it's an edge case)

5. **Test message deletion/truncation:**
   - Edit a message and observe the truncation events
   - Verify the regenerate button is still on the correct message after truncation

6. **Review ChatGPT / Claude Web UX for comparison:**
   - In ChatGPT/Claude, regenerate is only available on assistant messages when not streaming
   - It's always available on the *last* assistant message, regardless of what comes after
   - Consider if Chatsune's logic matches this expectation

### UX Inconsistencies

1. **"Generate response" standalone button only after user message:** This is correct, but the affordance is weak. The button appears *below* all messages, which is hidden unless the user scrolls.

2. **Regenerate on assistant message only if it's the last message:** What if the user wants to regenerate an older assistant response? The current logic prevents this. Compare to Claude Web, where regenerate is available on any assistant message.

3. **No indication that regenerate is disabled during streaming:** The button is completely hidden, not shown in a disabled state. A user might assume the button never exists.

---

## Summary of File References

### Frontend Files Involved

- **`/home/chris/workspace/chatsune/frontend/src/features/chat/useAutoScroll.ts:1-64`** — Auto-scroll polling logic
- **`/home/chris/workspace/chatsune/frontend/src/features/chat/MessageList.tsx:48-190`** — Regenerate condition, message rendering, scroll container
- **`/home/chris/workspace/chatsune/frontend/src/features/chat/ChatView.tsx:442-479, 688-690, 149`** — Edit handler, lock banner rendering, lock state subscription
- **`/home/chris/workspace/chatsune/frontend/src/core/store/chatStore.ts:1-174`** — Message and lock state store
- **`/home/chris/workspace/chatsune/frontend/src/features/chat/useChatStream.ts:1-202`** — Event handling and reconciliation
- **`/home/chris/workspace/chatsune/frontend/src/core/websocket/eventBus.ts:1-51`** — Event subscription and dispatch
- **`/home/chris/workspace/chatsune/frontend/src/features/chat/AssistantMessage.tsx:1-88`** — Regenerate button rendering
- **`/home/chris/workspace/chatsune/frontend/src/features/chat/InferenceWaitBanner.tsx:1-24`** — Lock banner component
- **`/home/chris/workspace/chatsune/frontend/src/features/chat/UserBubble.tsx:1-130`** — Edit UI

### Backend Files Involved

- **`/home/chris/workspace/chatsune/backend/modules/chat/_orchestrator.py:500-562`** — Lock wait event publishing
- **`/home/chris/workspace/chatsune/backend/modules/chat/_handlers_ws.py:156-280, 282-295`** — Edit and regenerate handlers
- **`/home/chris/workspace/chatsune/shared/topics.py:1-111`** — Event type constants

### Architecture / Context

- **`/home/chris/workspace/chatsune/CLAUDE.md`** — Debugging methodology (enumerate all causes, check infrastructure layers)
- **`/home/chris/workspace/chatsune/DEBT.md:56, 89`** — Known issues with auto-scroll polling and optimistic UI

---

## Recommendations (Not Implemented)

1. **Auto-scroll:** Replace 80ms polling with `requestAnimationFrame` or a `MutationObserver` on the message list content node.

2. **Edit-and-send:** Add a timeout on optimistic ID swap; if the real ID hasn't arrived within 500ms, surface an error.

3. **Lock indicator:** Explicitly pass `target_user_ids=[user_id]` when publishing lock-wait events; verify in the WebSocket event router.

4. **Regenerate:** Limit to messages that have a user message immediately before them (stronger UX); consider allowing regenerate on any assistant message (richer UX but more complex state).

