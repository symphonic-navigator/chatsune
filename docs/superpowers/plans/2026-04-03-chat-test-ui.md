# Chat Test UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a minimal chat UI to verify the full chat stack works end-to-end (REST + WebSocket + Streaming).

**Architecture:** A single ChatPage component at `/chat/:personaId` that creates a session on mount, sends messages via WebSocket, and displays streaming responses via eventBus subscriptions. No store — local React state only.

**Tech Stack:** React, TypeScript, Tailwind CSS, existing WebSocket infrastructure

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `frontend/src/core/api/chat.ts` | REST API calls for chat sessions/messages |
| Create | `frontend/src/prototype/pages/ChatPage.tsx` | Chat test page with message list and input |
| Modify | `frontend/src/core/websocket/connection.ts` | Add `sendMessage()` export for sending WebSocket messages |
| Modify | `frontend/src/prototype/pages/PersonasPage.tsx` | Add "Chat" button to persona cards |
| Modify | `frontend/src/App.tsx` | Add `/chat/:personaId` route |

---

### Task 1: Add WebSocket send function

**Files:**
- Modify: `frontend/src/core/websocket/connection.ts`

- [ ] **Step 1: Add `sendMessage` export to connection.ts**

Add after the existing `sendPing` function (line 101):

```typescript
export function sendMessage(message: Record<string, unknown>) {
  if (ws?.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(message))
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/core/websocket/connection.ts
git commit -m "Add sendMessage export to WebSocket connection"
```

---

### Task 2: Create chat API layer

**Files:**
- Create: `frontend/src/core/api/chat.ts`

- [ ] **Step 1: Create chat API module**

```typescript
import { api } from "./client"

interface ChatSessionDto {
  id: string
  user_id: string
  persona_id: string
  model_unique_id: string
  state: "idle" | "streaming" | "requires_action"
  created_at: string
  updated_at: string
}

interface ChatMessageDto {
  id: string
  session_id: string
  role: "user" | "assistant" | "tool"
  content: string
  thinking: string | null
  token_count: number
  created_at: string
}

export type { ChatSessionDto, ChatMessageDto }

export const chatApi = {
  createSession: (personaId: string) =>
    api.post<ChatSessionDto>("/api/chat/sessions", { persona_id: personaId }),

  getSession: (sessionId: string) =>
    api.get<ChatSessionDto>(`/api/chat/sessions/${sessionId}`),

  getMessages: (sessionId: string) =>
    api.get<ChatMessageDto[]>(`/api/chat/sessions/${sessionId}/messages`),
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/core/api/chat.ts
git commit -m "Add chat REST API layer"
```

---

### Task 3: Create ChatPage component

**Files:**
- Create: `frontend/src/prototype/pages/ChatPage.tsx`

- [ ] **Step 1: Create the ChatPage component**

```tsx
import { useState, useEffect, useRef } from "react"
import { useParams, useNavigate } from "react-router-dom"
import { chatApi } from "../../core/api/chat"
import type { ChatSessionDto, ChatMessageDto } from "../../core/api/chat"
import { eventBus } from "../../core/websocket/eventBus"
import { sendMessage } from "../../core/websocket/connection"

interface DisplayMessage {
  id: string
  role: "user" | "assistant"
  content: string
}

export default function ChatPage() {
  const { personaId } = useParams<{ personaId: string }>()
  const navigate = useNavigate()
  const [session, setSession] = useState<ChatSessionDto | null>(null)
  const [messages, setMessages] = useState<DisplayMessage[]>([])
  const [input, setInput] = useState("")
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [contextStatus, setContextStatus] = useState<string | null>(null)
  const streamingContentRef = useRef("")
  const correlationRef = useRef<string | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, streaming])

  // Create session on mount
  useEffect(() => {
    if (!personaId) return

    let cancelled = false
    chatApi.createSession(personaId).then((s) => {
      if (!cancelled) setSession(s)
    }).catch((err) => {
      if (!cancelled) setError(err.message ?? "Failed to create session")
    })

    return () => { cancelled = true }
  }, [personaId])

  // Subscribe to chat events
  useEffect(() => {
    const unsubs = [
      eventBus.on("chat.stream.started", (event) => {
        const payload = event.payload as { session_id: string; correlation_id: string }
        if (payload.session_id !== session?.id) return
        correlationRef.current = event.correlation_id
        streamingContentRef.current = ""
        setStreaming(true)
        setError(null)
        // Add empty assistant message placeholder
        setMessages((prev) => [...prev, { id: "streaming", role: "assistant", content: "" }])
      }),

      eventBus.on("chat.content.delta", (event) => {
        if (event.correlation_id !== correlationRef.current) return
        const payload = event.payload as { delta: string }
        streamingContentRef.current += payload.delta
        const content = streamingContentRef.current
        setMessages((prev) =>
          prev.map((m) => m.id === "streaming" ? { ...m, content } : m)
        )
      }),

      eventBus.on("chat.stream.ended", (event) => {
        if (event.correlation_id !== correlationRef.current) return
        const payload = event.payload as { status: string; context_status: string }
        setStreaming(false)
        setContextStatus(payload.context_status)
        // Replace streaming placeholder with final message
        setMessages((prev) =>
          prev.map((m) => m.id === "streaming" ? { ...m, id: `msg-${Date.now()}` } : m)
        )
        correlationRef.current = null
      }),

      eventBus.on("chat.stream.error", (event) => {
        if (event.correlation_id !== correlationRef.current) return
        const payload = event.payload as { user_message: string }
        setStreaming(false)
        setError(payload.user_message)
        // Remove streaming placeholder
        setMessages((prev) => prev.filter((m) => m.id !== "streaming"))
        correlationRef.current = null
      }),
    ]

    return () => unsubs.forEach((unsub) => unsub())
  }, [session?.id])

  const handleSend = () => {
    if (!input.trim() || !session || streaming) return

    const text = input.trim()
    setInput("")

    // Optimistic: add user message
    setMessages((prev) => [...prev, { id: `user-${Date.now()}`, role: "user", content: text }])

    // Send via WebSocket
    sendMessage({
      type: "chat.send",
      session_id: session.id,
      content: [{ type: "text", text }],
    })
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  if (error && !session) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4">
        <p className="text-red-600">{error}</p>
        <button onClick={() => navigate("/personas")} className="text-sm text-blue-600 hover:underline">
          Back to Personas
        </button>
      </div>
    )
  }

  if (!session) {
    return <p className="text-sm text-gray-400">Creating session...</p>
  }

  return (
    <div className="flex flex-col h-[calc(100vh-8rem)]">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-gray-200 pb-3 mb-3">
        <div>
          <button onClick={() => navigate("/personas")} className="text-sm text-blue-600 hover:underline mr-4">
            &larr; Back
          </button>
          <span className="text-sm text-gray-500">Session: {session.id.slice(0, 8)}...</span>
        </div>
        {contextStatus && (
          <span className={`text-xs px-2 py-1 rounded ${
            contextStatus === "green" ? "bg-green-100 text-green-700" :
            contextStatus === "yellow" ? "bg-yellow-100 text-yellow-700" :
            contextStatus === "orange" ? "bg-orange-100 text-orange-700" :
            "bg-red-100 text-red-700"
          }`}>
            Context: {contextStatus}
          </span>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto space-y-3 pb-4">
        {messages.length === 0 && (
          <p className="text-sm text-gray-400 text-center mt-8">Send a message to start chatting.</p>
        )}
        {messages.map((msg) => (
          <div key={msg.id} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[70%] rounded-lg px-4 py-2 text-sm whitespace-pre-wrap ${
              msg.role === "user"
                ? "bg-blue-600 text-white"
                : "bg-gray-100 text-gray-800"
            }`}>
              {msg.content || (msg.id === "streaming" ? "..." : "")}
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Error banner */}
      {error && (
        <div className="text-sm text-red-600 bg-red-50 rounded px-3 py-2 mb-2">{error}</div>
      )}

      {/* Input */}
      <div className="flex gap-2 border-t border-gray-200 pt-3">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type a message..."
          rows={1}
          disabled={streaming}
          className="flex-1 rounded border border-gray-300 px-3 py-2 text-sm resize-none focus:border-blue-500 focus:outline-none disabled:opacity-50"
        />
        <button
          onClick={handleSend}
          disabled={streaming || !input.trim()}
          className="rounded bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
        >
          Send
        </button>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/prototype/pages/ChatPage.tsx
git commit -m "Add prototype ChatPage component with streaming support"
```

---

### Task 4: Add Chat button to PersonasPage and register route

**Files:**
- Modify: `frontend/src/prototype/pages/PersonasPage.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Add Chat button to PersonaCard**

In `PersonasPage.tsx`, add `useNavigate` import and a Chat button to the PersonaCard component.

Add to imports (line 1):
```typescript
import { useNavigate } from "react-router-dom"
```

In the `PersonaCard` component, add `navigate` and a Chat button in the button group (alongside Edit and Delete):
```typescript
function PersonaCard({
  persona,
  onEdit,
  onDelete,
}: {
  persona: PersonaDto
  onEdit: (p: PersonaDto) => void
  onDelete: (id: string) => void
}) {
  const navigate = useNavigate()

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="flex items-start justify-between">
        <div>
          <h3 className="font-medium text-sm">{persona.name}</h3>
          <p className="text-xs text-gray-500 mt-0.5">{persona.tagline}</p>
        </div>
        <div className="flex gap-1">
          <button onClick={() => navigate(`/chat/${persona.id}`)} className="rounded bg-green-100 px-2 py-1 text-xs text-green-700 hover:bg-green-200">Chat</button>
          <button onClick={() => onEdit(persona)} className="rounded bg-gray-100 px-2 py-1 text-xs hover:bg-gray-200">Edit</button>
          <button onClick={() => onDelete(persona.id)} className="rounded bg-red-100 px-2 py-1 text-xs text-red-700 hover:bg-red-200">Delete</button>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-2 text-xs text-gray-500">
        <span className="rounded bg-gray-50 px-2 py-0.5">{persona.model_unique_id}</span>
        <span className="rounded bg-gray-50 px-2 py-0.5">temp: {persona.temperature}</span>
        {persona.reasoning_enabled && <span className="rounded bg-blue-50 px-2 py-0.5 text-blue-600">reasoning</span>}
        {persona.colour_scheme && <span className="rounded bg-gray-50 px-2 py-0.5">colour: {persona.colour_scheme}</span>}
        <span className="rounded bg-gray-50 px-2 py-0.5">order: {persona.display_order}</span>
      </div>
      <p className="mt-2 text-xs text-gray-400 line-clamp-2">{persona.system_prompt}</p>
    </div>
  )
}
```

- [ ] **Step 2: Add ChatPage route to App.tsx**

Add ChatPage import (after line 11):
```typescript
import ChatPage from "./prototype/pages/ChatPage"
```

Add route (after the `/personas` route, line 40):
```tsx
<Route path="/chat/:personaId" element={<ChatPage />} />
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/prototype/pages/PersonasPage.tsx frontend/src/App.tsx
git commit -m "Add Chat button to persona cards and register chat route"
```

---

### Task 5: Verify in browser

- [ ] **Step 1: Start the stack**

```bash
docker compose up -d
cd frontend && pnpm dev
```

- [ ] **Step 2: Manual verification checklist**

1. Navigate to `/personas` — verify Chat button appears on each persona card
2. Click Chat on a persona — verify redirect to `/chat/:personaId`
3. Verify "Creating session..." appears briefly, then chat UI loads
4. Type a message and press Enter — verify it appears as a blue bubble on the right
5. Verify streaming response appears on the left, text arriving incrementally
6. Verify context status badge appears after response completes (green/yellow/orange/red)
7. Send another message — verify conversation flows correctly
8. If an error occurs, verify the red error banner is shown

- [ ] **Step 3: Final commit (if any fixes needed)**

```bash
git add -A
git commit -m "Fix chat test UI issues"
```
