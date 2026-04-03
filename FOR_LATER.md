# Chatsune — Deferred Features

Features that are designed or considered but intentionally deferred.
Each entry explains what it is and why it is not needed yet.

---

## Context Synopsis & Continue

**What:** When a chat session hits the 80% context limit, offer the user a
"Summarise & Continue" action. The backend runs an LLM call to produce a
compactified synopsis of the conversation, creates a new session, and injects
the synopsis as a context prolog. The user continues seamlessly with full
awareness of what happened before — but in a fresh context window.

**Why deferred:** Needs its own design cycle. The synopsis quality depends on
a good summarisation prompt, and the "context prolog" injection mechanism
needs careful thought (it is not a regular message — it is injected context
that the model should treat as background, not as a conversation turn).

**Why it matters:** This is a differentiating feature. No major chat UI handles
context exhaustion gracefully — they either silently drop messages (rolling
window) or just block. "Context prefill with compactified synopsis" gives users
a seamless experience while being honest about what the model knows.

---

## Tool Calls (Server-Side & Client-Side)

**What:** Server-side tools auto-execute (max 5 iterations). Client-side tools
pause the stream and wait for the frontend to submit results via
`chat.tool_result`. The adapter pattern and `ToolCallEvent` / `ToolDefinition`
models already exist.

**Why deferred:** The inference loop works end-to-end without tools. Tools are a
separate feature with their own complexity (execution sandbox, permission model,
tool registry, client-side pause/resume protocol).

---

## Memory System (Replaces RAG)

**What:** Long-term memory via tool-based retrieval. Models query their own
memory store via tools rather than having pre-selected RAG context injected.
The `<usermemory>` system prompt layer is reserved for this.

**Why this approach:** Blockbuster models confirm they prefer tool-based
retrieval over injected RAG context. Query construction is not a problem for
them, and tool-based retrieval gives the model agency over what it retrieves.

**Why deferred:** Needs tool system first. The memory store, consolidation
pipeline, and retrieval tools are a substantial feature set.

---

## Attachments (Images, Files)

**What:** Users can attach images and files to messages. The `ContentPart`
model already supports `type: "image"` with `data` and `media_type` fields.

**Why deferred:** Needs upload infrastructure (blob storage or GridFS), size
limits, expiry policy, and vision model detection. The inference pipeline
handles multimodal content parts already — only the upload path is missing.

---

## Additional Providers

**What:** Beyond Ollama Cloud — OpenAI, Anthropic, Mistral, local Ollama, etc.
The `ADAPTER_REGISTRY` pattern supports adding providers by implementing
`BaseAdapter.stream_completion()`.

**Why deferred:** One provider is sufficient to validate the full stack.
Additional providers are mechanical once the pattern is proven.

---

## Session Cloning

**What:** Explicitly fork a conversation by cloning a session up to a specific
message. Creates a new session with copied message history. This is the
explicit alternative to implicit message branching.

**Why deferred:** Edit with truncation covers the primary use case. Cloning is
a convenience feature for power users who want to explore alternatives without
losing the original conversation.

---

## Notification Bell & Flyout

**What:** A bell icon in the top-right corner with an unread badge count and a
flyout panel showing persistent notification history. Notifications would persist
across page navigation and show relative timestamps ("5m ago", "2h ago").
The previous prototype (chat-client-02) had this fully implemented with a
Zustand store, NotificationBell, and NotificationFlyout components.

**Why deferred:** The toast-only system is sufficient for the prototype. The bell
and flyout add complexity (read/unread state, flyout positioning, click-outside
dismiss) without validating new patterns. The toast store already supports the
data model needed — adding the bell/flyout is a UI-only extension.

---

## Backend-Driven Notifications

**What:** The backend publishes notification events via WebSocket (e.g. embedding
job completed, consolidation failed). The frontend notification store subscribes
to these events and creates toasts/entries automatically.

**Why deferred:** There are no background jobs yet that would produce
notifications. When the memory consolidation pipeline or other async processes
are added, this becomes relevant.
