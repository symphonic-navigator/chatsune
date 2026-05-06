# QA Paket B — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two related frontend bugs reported by Ksena (QA): the
chat view stays mounted when the active chat is deleted from any
"settings" UI surface, and the persona-overlay history hides chats
that belong to a project.

**Architecture:** Both fixes are frontend-only. Bug #3 adds an
`eventBus` subscription to `CHAT_SESSION_DELETED` inside `ChatView`,
mirroring the same subscription pattern already used at
`useChatSessions.ts:55-58`. Bug #4 swaps the persona-overlay
HistoryTab's reliance on `useChatSessions` (intentionally global,
non-project) for a dedicated `chatApi.listSessions({
include_project_chats: true })` fetch with client-side persona
filtering, plus an inline project pill mirroring the user-modal
HistoryTab pattern.

**Tech Stack:** React + TypeScript (TSX), Vite, react-router-dom v6
(`useNavigate`), pnpm. Existing event bus at
`frontend/src/core/websocket/eventBus.ts`, topic constants at
`frontend/src/core/types/events.ts`, projects store at
`frontend/src/features/projects/useProjectsStore.ts`.

**Spec:** `devdocs/specs/2026-05-06-qa-paket-b-chat-list-sync-design.md`

**Subagent constraint:** Per project memory, subagents must NOT
merge, push, or switch branches. Implement on the feature branch
the controller created. The dispatching agent will handle merging.

---

## File map

```
frontend/src/
  features/chat/ChatView.tsx                        [MODIFY] — Task 1
  app/components/persona-overlay/HistoryTab.tsx     [MODIFY] — Task 2
```

The two tasks touch separate files — sequential dispatch only (per
the subagent-driven-development skill rule "never dispatch multiple
implementer subagents in parallel"). No file conflicts.

No automated tests are added. Both changes are surface-level
state-sync fixes; manual verification on a real device is the
primary check, matching the convention from QA Paket A.

---

## Task 1: Reactive `CHAT_SESSION_DELETED` listener in `ChatView` (Bug #3)

**Files:**
- Modify: `frontend/src/features/chat/ChatView.tsx`

- [ ] **Step 1: Locate the relevant landmarks in `ChatView.tsx`**

Confirm:

- `useNavigate` is imported (line 2) and `navigate` is bound somewhere in the component body (search for `const navigate = useNavigate()`).
- `sessionId` is in scope (it comes from `useParams()` — search the component body for `sessionId`).
- `isIncognito` is declared at line 137: `const isIncognito = searchParams.get('incognito') === '1'`.
- `eventBus` and `Topics` are NOT yet imported in this file.

- [ ] **Step 2: Add the imports for `eventBus` and `Topics`**

At the top of `ChatView.tsx`, alongside the other `core/` imports, add:

```ts
import { eventBus } from '../../core/websocket/eventBus'
import { Topics } from '../../core/types/events'
```

Match the relative path style used by the surrounding imports
(`'../../core/...'` — confirm by reading lines 1-30).

If `BaseEvent` is not already imported and you need its type for the
handler signature, also add:

```ts
import type { BaseEvent } from '../../core/types/events'
```

(The reference subscription at `useChatSessions.ts:55` types its
handler as `(event: BaseEvent) => ...`.)

- [ ] **Step 3: Add the reactive listener `useEffect`**

Place this effect inside the `ChatView` component body, after
`isIncognito` is in scope (i.e. anywhere after line 137) and after
`navigate` and `sessionId` are bound. A natural spot is alongside
the other `useEffect`s that depend on `sessionId`. Body:

```tsx
// Bug fix: when the active chat session is deleted server-side
// (from sidebar or any settings UI), navigate the chat view away.
// This is the reactive piece the sidebar's imperative `navigate(...)`
// has been silently relying on. By subscribing to the event directly
// rather than watching a session-list store, we cover both global
// and project-bound chats — useChatSessions deliberately excludes
// project chats from its store.
useEffect(() => {
  if (isIncognito) return
  if (!sessionId) return
  const unsub = eventBus.on(Topics.CHAT_SESSION_DELETED, (event: BaseEvent) => {
    if (event.payload.session_id === sessionId) {
      navigate('/personas')
    }
  })
  return unsub
}, [sessionId, isIncognito, navigate])
```

Notes:
- The `if (isIncognito) return` guard is defence in depth: incognito
  uses an ephemeral local UUID never sent server-side, so no
  matching delete event will arrive. The early return makes the
  intent explicit.
- The `if (!sessionId) return` guard avoids subscribing on routes
  where no session is open yet (e.g. `/chat/{persona}` without a
  session id during creation).
- The `navigate` target `/personas` matches the sidebar's existing
  delete handler at `Sidebar.tsx:308`.
- Do NOT type-narrow `event.payload.session_id` beyond the
  comparison — the existing pattern at `useChatSessions.ts:56` uses
  `event.payload.session_id as string`. If your TS strictness flags
  the comparison, mirror that cast.

- [ ] **Step 4: Build verification**

Run from `frontend/`:

```bash
pnpm run build
```

Expected: clean build, no TypeScript errors. (`tsc -b` is the
strict check — `pnpm tsc --noEmit` is insufficient per project
convention.)

- [ ] **Step 5: Manual verification (skipped for subagent)**

The controller will manually verify on a real device per the spec.
You only need to ensure the build passes.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/chat/ChatView.tsx
git commit -m "Navigate chat view away when active session is deleted server-side"
```

---

## Task 2: Persona-overlay HistoryTab includes project chats with pill (Bug #4)

**Files:**
- Modify: `frontend/src/app/components/persona-overlay/HistoryTab.tsx`

- [ ] **Step 1: Locate the relevant structure**

Open `frontend/src/app/components/persona-overlay/HistoryTab.tsx`
and confirm:

- Line 4: `import { useChatSessions } from '../../../core/hooks/useChatSessions'`
- Line 53: `const { sessions, isLoading } = useChatSessions()`
- Line 94: `return sessions.filter((s) => s.persona_id === persona.id)`
- Lines 134-141: the `<SessionRow>` invocation in the list body — only `session`, `chakra`, `onOpen` are passed today.
- Lines 256-287: the `SessionRow` component's main `<button>` block — the title `<p>` is at line 279-281.

The existing user-modal HistoryTab is the reference pattern:

- `app/components/user-modal/HistoryTab.tsx:8` — `import { useProjectsStore } from '../../../features/projects/useProjectsStore'`
- `app/components/user-modal/HistoryTab.tsx:9` — `import { eventBus } from '../../../core/websocket/eventBus'`
- `app/components/user-modal/HistoryTab.tsx:10` — `import { Topics } from '../../../core/types/events'`
- `app/components/user-modal/HistoryTab.tsx:100` — `const projects = useProjectsStore((s) => s.projects)`
- `app/components/user-modal/HistoryTab.tsx:140-142` — the dedicated fetch shape:
  ```ts
  const res = await chatApi.listSessions({
    project_id: projectFilter,
    include_project_chats: !projectFilter && includeProjectChats,
  })
  ```
- `app/components/user-modal/HistoryTab.tsx:351-353` — the project lookup:
  ```ts
  const project = showProjectPill && s.project_id
    ? projects[s.project_id] ?? null
    : null
  ```
- `app/components/user-modal/HistoryTab.tsx:535-543` — the pill JSX (full snippet quoted in Step 4 below).

- [ ] **Step 2: Replace `useChatSessions` with a dedicated fetch**

In `persona-overlay/HistoryTab.tsx`, replace the `useChatSessions`
import (line 4) and its usage (line 53) with:

Add imports at the top of the file (alongside the existing
`core/api/chat` import):

```ts
import { eventBus } from '../../../core/websocket/eventBus'
import { Topics, type BaseEvent } from '../../../core/types/events'
import { useProjectsStore } from '../../../features/projects/useProjectsStore'
```

Remove the `useChatSessions` import (line 4) entirely — no other
uses remain in this file after this task.

Replace the `useChatSessions()` call (line 53) and the
`filtered` derivation (lines 90-95) with local state plus a
fetch effect plus a delete subscription:

```tsx
const [sessions, setSessions] = useState<ChatSessionDto[]>([])
const [isLoading, setIsLoading] = useState(false)
const projects = useProjectsStore((s) => s.projects)

// Fetch this persona's full chat history (including project-bound
// chats). useChatSessions intentionally excludes project chats —
// see useChatSessions.ts:32-34. We do our own fetch here, mirroring
// the user-modal HistoryTab's pattern at HistoryTab.tsx:140-142.
useEffect(() => {
  let cancelled = false
  setIsLoading(true)
  chatApi
    .listSessions({ include_project_chats: true })
    .then((res) => {
      if (cancelled) return
      const forPersona = res
        .filter((s) => s.persona_id === persona.id)
        .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
      setSessions(forPersona)
    })
    .catch(() => {
      // Empty list on failure — matches useChatSessions's silent-fail style.
    })
    .finally(() => {
      if (!cancelled) setIsLoading(false)
    })
  return () => {
    cancelled = true
  }
}, [persona.id])

// Live update on delete: when any session for this persona is
// deleted, drop it from the local list. This pairs with the new
// reactive listener in ChatView (Task 1) so the persona-overlay
// HistoryTab does not show stale rows.
useEffect(() => {
  const unsub = eventBus.on(Topics.CHAT_SESSION_DELETED, (event: BaseEvent) => {
    const sessionId = event.payload.session_id as string
    setSessions((prev) => prev.filter((s) => s.id !== sessionId))
  })
  return unsub
}, [])
```

Then update the `filtered` derivation (the `useMemo` at lines
90-95) to drop the persona filter (already applied at fetch time):

```tsx
const filtered = useMemo(() => {
  if (searchResults !== null) {
    return searchResults
  }
  return sessions
}, [sessions, searchResults])
```

- [ ] **Step 3: Pass the project pill data into `SessionRow`**

Update the `SessionRow` invocation at the list site (currently
lines 134-141) to pass the resolved project pill:

```tsx
{groupSessions.map((s) => {
  const project = s.project_id ? projects[s.project_id] ?? null : null
  return (
    <SessionRow
      key={s.id}
      session={s}
      chakra={chakra}
      onOpen={() => handleOpen(s)}
      projectPill={project ? { emoji: project.emoji, title: project.title } : null}
    />
  )
})}
```

Update the `SessionRowProps` interface (currently lines 150-154) to
declare the new optional prop:

```tsx
interface SessionRowProps {
  session: ChatSessionDto
  chakra: ChakraPaletteEntry
  onOpen: () => void
  projectPill: { emoji: string | null; title: string } | null
}
```

Update the `SessionRow` function signature (currently line 156) to
destructure the new prop:

```tsx
function SessionRow({ session, chakra, onOpen, projectPill }: SessionRowProps) {
```

- [ ] **Step 4: Render the pill inside the `SessionRow`**

Inside the `SessionRow`'s main button, the title currently lives at
lines 278-282 in this exact form:

```tsx
) : (
  <p className="text-[13px] text-white/65 group-hover:text-white/80 truncate transition-colors">
    {session.title ?? formatDate(session.updated_at)}
  </p>
)}
```

Wrap the existing `<p>` and the new pill in a fragment so both
appear inline (mirroring the user-modal HistoryTab structure at
`HistoryTab.tsx:530-544`):

```tsx
) : (
  <>
    <p className="text-[13px] text-white/65 group-hover:text-white/80 truncate transition-colors">
      {session.title ?? formatDate(session.updated_at)}
    </p>
    {projectPill && (
      <span
        data-testid="history-project-pill"
        className="ml-1 flex-shrink-0 rounded px-1.5 py-0.5 font-mono text-[10px] text-white/65"
        style={{ background: 'rgba(255,255,255,0.05)' }}
      >
        {projectPill.emoji ?? '—'} {projectPill.title}
      </span>
    )}
  </>
)}
```

The pill JSX is copied verbatim from
`app/components/user-modal/HistoryTab.tsx:535-543` — same
`data-testid`, same classes, same inline style, same fallback
emoji. Do not deviate.

- [ ] **Step 5: Determine if `ChatSessionDto` is already imported**

The fetch above uses `ChatSessionDto`. Confirm `import { chatApi,
type ChatSessionDto } from '../../../core/api/chat'` is already
present (line 3 of the existing file). It is — no import change
needed.

Confirm `useState` is already imported (it is — line 1).

- [ ] **Step 6: Build verification**

Run from `frontend/`:

```bash
pnpm run build
```

Expected: clean build, no TypeScript errors.

If `useProjectsStore`'s shape is `Record<string, ProjectDto>` and
`ProjectDto.emoji` / `.title` are typed as `string | null` and
`string` respectively, the JSX above is correct. If the actual
types differ, adjust the local interface to match — do NOT change
the projects store. (The user-modal HistoryTab uses exactly this
pattern and builds clean, so the shapes line up.)

- [ ] **Step 7: Manual verification (skipped for subagent)**

The controller will manually verify per the spec.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/app/components/persona-overlay/HistoryTab.tsx
git commit -m "Show project chats in persona-overlay history with project pill"
```

---

## Self-review

**Spec coverage:**
- Spec §1 (Bug #3): Task 1 implements the event-bus subscription in ChatView with the required guards (isIncognito, sessionId match) and `/personas` navigation target.
- Spec §2 (Bug #4): Task 2 replaces `useChatSessions` with a dedicated fetch, applies persona filter at fetch time, subscribes to delete events, renders the project pill verbatim from the user-modal HistoryTab pattern, and explicitly does NOT add a toggle.

**Placeholder scan:** None. All code blocks are complete; line
references are content-anchored where the file-line numbers may
shift under prior edits.

**Type consistency:** `BaseEvent` import path matches the user-modal
HistoryTab usage; `ChatSessionDto` import is already present in the
target file. The `projectPill` prop shape matches the user-modal
HistoryTab's resolved value.
