# Chat Test UI — Design Spec

**Date:** 2026-04-03
**Goal:** Verify the full chat stack works end-to-end (REST + WebSocket + Inference + Streaming) with a minimal prototype UI.

This is a throwaway test UI. The real chat implementation follows in the next session.

---

## Scope

### In scope

- **ChatPage** at `/chat/:personaId` — creates a session, sends messages, displays streaming responses
- **"Chat" button** on each persona card in PersonasPage — navigates to ChatPage
- **API layer** (`core/api/chat.ts`) for REST calls (create session, list messages)
- **Local React state** — no Zustand store needed for a test

### Out of scope

- Edit, regenerate, cancel
- Session switching or session list
- Thinking/reasoning display
- Design quality (functional only)
- Persistent chat history across page navigations

---

## Components

### 1. ChatPage (`prototype/pages/ChatPage.tsx`)

**Route:** `/chat/:personaId`

**Lifecycle:**
1. On mount, call `POST /api/chat/sessions` with `{ persona_id }` to create a new session
2. Store `session_id` in local state
3. Display a message input and a scrollable message list

**Sending messages:**
- User types message, presses Enter or clicks Send
- Send via WebSocket: `{ type: "chat.send", session_id, content: [{ type: "text", text }] }`
- Append user message to local state immediately (optimistic)

**Receiving responses:**
- Subscribe to `chat.stream.started` — show loading indicator
- Subscribe to `chat.content.delta` — append delta text to current assistant message
- Subscribe to `chat.stream.ended` — finalise message, show context status (green/yellow/orange/red)
- Subscribe to `chat.stream.error` — display error message

**Display:**
- Simple message list: user messages right-aligned or prefixed, assistant messages left-aligned or prefixed
- Current streaming text shown as it arrives
- Context status indicator after stream ends
- Error display for failed streams

### 2. Persona card "Chat" button (`PersonasPage.tsx`)

- Add a "Chat" button to each persona card
- On click: `navigate(`/chat/${persona.id}`)`

### 3. API layer (`core/api/chat.ts`)

```typescript
createSession(personaId: string): Promise<ChatSessionDto>
getSession(sessionId: string): Promise<ChatSessionDto>
getMessages(sessionId: string): Promise<ChatMessageDto[]>
```

Uses the existing `client.ts` authenticated fetch wrapper.

### 4. Route registration (`App.tsx`)

Add route: `/chat/:personaId` → `ChatPage`

---

## Event flow

```
User types message
  → WebSocket: chat.send { session_id, content }
  ← WebSocket: chat.stream.started { session_id, correlation_id }
  ← WebSocket: chat.content.delta { correlation_id, delta } (repeated)
  ← WebSocket: chat.stream.ended { correlation_id, status, context_status }
```

---

## Files to create/modify

| Action | File |
|--------|------|
| Create | `frontend/src/core/api/chat.ts` |
| Create | `frontend/src/prototype/pages/ChatPage.tsx` |
| Modify | `frontend/src/prototype/pages/PersonasPage.tsx` (add Chat button) |
| Modify | `frontend/src/App.tsx` (add route) |
