# UX-008 & UX-009 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace hover-only message action buttons with a permanent action bar (UX-008) and replace the UserModal-based collapsed sidebar navigation with flyout panels for Projects/History (UX-009).

**Architecture:** UX-008 moves action buttons from absolutely-positioned hover overlays to inline action bars inside each message bubble. UX-009 adds a `SidebarFlyout` component that renders a 260px panel adjacent to the collapsed sidebar, replacing `onOpenModal` calls for Projects and History icons.

**Tech Stack:** React, TypeScript, Tailwind CSS

---

### Task 1: UX-008 — Permanent action bar in AssistantMessage

**Files:**
- Modify: `frontend/src/features/chat/AssistantMessage.tsx`

- [ ] **Step 1: Replace hover buttons with inline action bar**

Replace the entire content of `AssistantMessage.tsx` with:

```tsx
import { useCallback, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { createMarkdownComponents } from './markdownComponents'
import { ThinkingBubble } from './ThinkingBubble'
import type { Highlighter } from 'shiki'

interface AssistantMessageProps {
  content: string; thinking: string | null; isStreaming: boolean;
  accentColour: string; highlighter: Highlighter | null;
  thinkingDefaultExpanded?: boolean; onThinkingToggle?: (expanded: boolean) => void;
  isBookmarked?: boolean; onBookmark?: () => void;
}

export function AssistantMessage({ content, thinking, isStreaming, accentColour, highlighter, thinkingDefaultExpanded, onThinkingToggle, isBookmarked, onBookmark }: AssistantMessageProps) {
  const [copied, setCopied] = useState(false)

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(content)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }, [content])

  const components = createMarkdownComponents(highlighter)

  return (
    <div className="animate-message-entrance">
      {thinking && (
        <ThinkingBubble content={thinking} isStreaming={isStreaming && !content} accentColour={accentColour}
          defaultExpanded={thinkingDefaultExpanded} onToggle={onThinkingToggle} />
      )}
      <div className="max-w-[85%]">
        <div className="chat-text chat-prose text-white/80">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
            {content}
          </ReactMarkdown>
        </div>
        {!isStreaming && content && (
          <div className="mt-2.5 flex gap-3 border-t border-white/6 pt-2">
            <button type="button" onClick={handleCopy}
              className="flex items-center gap-1 text-[11px] text-white/25 transition-colors hover:text-white/50"
              title={copied ? 'Copied!' : 'Copy message'}>
              {copied ? (
                <svg width="13" height="13" viewBox="0 0 14 14" fill="none">
                  <path d="M3 7L6 10L11 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              ) : (
                <svg width="13" height="13" viewBox="0 0 14 14" fill="none">
                  <rect x="4" y="4" width="8" height="8" rx="1.5" stroke="currentColor" strokeWidth="1.2" />
                  <path d="M10 4V2.5C10 1.5 9.55 1.5 9 1.5H2.5C1.95 1.5 1.5 1.95 1.5 2.5V9C1.5 9.55 1.95 10 2.5 10H4" stroke="currentColor" strokeWidth="1.2" />
                </svg>
              )}
              {copied ? 'Copied' : 'Copy'}
            </button>
            {onBookmark && (
              <button type="button" onClick={onBookmark}
                className={`flex items-center gap-1 text-[11px] transition-colors ${isBookmarked ? 'text-gold' : 'text-white/25 hover:text-white/50'}`}
                title={isBookmarked ? 'Bookmarked' : 'Bookmark'}>
                <svg width="13" height="13" viewBox="0 0 14 14" fill={isBookmarked ? 'currentColor' : 'none'}>
                  <path d="M3 1.5H11V12.5L7 9.5L3 12.5V1.5Z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
                </svg>
                {isBookmarked ? 'Bookmarked' : 'Bookmark'}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
```

Key changes:
- Removed `isHovered` state, `onMouseEnter`/`onMouseLeave`, `group` class, `relative` on inner div
- Removed `absolute -right-8 top-1` positioned hover overlay
- Added inline action bar after message content with `border-t border-white/6`
- Actions: icon (13x13) + text label, `text-white/25` base, `hover:text-white/50`
- Action bar only renders when `!isStreaming && content`

- [ ] **Step 2: Build and verify**

Run: `cd frontend && pnpm run build 2>&1 | grep "AssistantMessage"`
Expected: No errors related to AssistantMessage

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/chat/AssistantMessage.tsx
git commit -m "UX-008: Replace hover actions with permanent action bar in AssistantMessage"
```

---

### Task 2: UX-008 — Permanent action bar in UserBubble

**Files:**
- Modify: `frontend/src/features/chat/UserBubble.tsx`

- [ ] **Step 1: Replace hover buttons with inline action bar**

Replace lines 60-94 (the non-editing return block) in `UserBubble.tsx` with:

```tsx
  return (
    <div data-testid="user-bubble" className="flex justify-end animate-message-entrance">
      <div className="max-w-[80%]">
        <div className="rounded-2xl rounded-tr-sm bg-white/8 px-4 py-2.5">
          <p className="chat-text whitespace-pre-wrap text-white/90">{content}</p>
          {attachments && attachments.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {attachments.map((att) => (
                <AttachmentChip key={att.file_id} attachment={att} />
              ))}
            </div>
          )}
          {isEditable && (
            <div className="mt-2.5 flex gap-3 border-t border-white/6 pt-2">
              <button type="button" data-testid="edit-button" onClick={startEdit}
                className="flex items-center gap-1 text-[11px] text-white/25 transition-colors hover:text-white/50"
                title="Edit message">
                <svg width="13" height="13" viewBox="0 0 14 14" fill="none">
                  <path d="M10.5 1.5L12.5 3.5L4 12H2V10L10.5 1.5Z" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                Edit
              </button>
              {onBookmark && (
                <button type="button" onClick={onBookmark}
                  className={`flex items-center gap-1 text-[11px] transition-colors ${isBookmarked ? 'text-gold' : 'text-white/25 hover:text-white/50'}`}
                  title={isBookmarked ? 'Bookmarked' : 'Bookmark'}>
                  <svg width="13" height="13" viewBox="0 0 14 14" fill={isBookmarked ? 'currentColor' : 'none'}>
                    <path d="M3 1.5H11V12.5L7 9.5L3 12.5V1.5Z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
                  </svg>
                  {isBookmarked ? 'Bookmarked' : 'Bookmark'}
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
```

Key changes:
- Removed `isHovered` state and `onMouseEnter`/`onMouseLeave` handlers (keep `isEditing`/`editText`/etc.)
- Removed `group` class, `relative` on inner div
- Removed `absolute -left-8 top-1` positioned hover overlay
- Added inline action bar inside the bubble (inside the `rounded-2xl` div), below content/attachments
- Action bar renders when `isEditable` (same condition as before, minus hover)
- Actions: icon (13x13) + text label, same styling as AssistantMessage

Also remove the now-unused `isHovered` state declaration from line 15. The `setIsHovered` calls are already gone from the JSX.

- [ ] **Step 2: Build and verify**

Run: `cd frontend && pnpm run build 2>&1 | grep "UserBubble"`
Expected: No errors related to UserBubble

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/chat/UserBubble.tsx
git commit -m "UX-008: Replace hover actions with permanent action bar in UserBubble"
```

---

### Task 3: UX-009 — Create SidebarFlyout component

**Files:**
- Create: `frontend/src/app/components/sidebar/SidebarFlyout.tsx`

- [ ] **Step 1: Create the SidebarFlyout component**

Create `frontend/src/app/components/sidebar/SidebarFlyout.tsx`:

```tsx
import { useEffect, type ReactNode } from 'react'

interface SidebarFlyoutProps {
  title: string
  onClose: () => void
  onOpenFullView: () => void
  children: ReactNode
}

export function SidebarFlyout({ title, onClose, onOpenFullView, children }: SidebarFlyoutProps) {
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-30 bg-black/40"
        onClick={onClose}
      />

      {/* Panel */}
      <div className="fixed left-[50px] top-0 z-40 flex h-full w-[260px] flex-col border-r border-white/8 bg-[#1a1a30] shadow-xl">
        {/* Header */}
        <div className="flex flex-shrink-0 items-center justify-between border-b border-white/6 px-4 py-3">
          <span className="text-[12px] font-semibold uppercase tracking-wider text-white/70">
            {title}
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onOpenFullView}
              className="rounded border border-white/10 px-2 py-0.5 text-[10px] text-white/40 transition-colors hover:border-white/20 hover:text-white/60"
            >
              Open full view
            </button>
            <button
              type="button"
              onClick={onClose}
              className="flex h-5 w-5 items-center justify-center rounded text-white/30 transition-colors hover:text-white/60"
            >
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                <path d="M2 2L10 10M10 2L2 10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto [&::-webkit-scrollbar]:w-[3px] [&::-webkit-scrollbar-thumb]:rounded-sm [&::-webkit-scrollbar-thumb]:bg-white/10">
          {children}
        </div>
      </div>
    </>
  )
}
```

- [ ] **Step 2: Build and verify**

Run: `cd frontend && pnpm run build 2>&1 | grep "SidebarFlyout"`
Expected: No errors (file is created but not yet imported anywhere)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/components/sidebar/SidebarFlyout.tsx
git commit -m "UX-009: Create SidebarFlyout shell component"
```

---

### Task 4: UX-009 — Integrate flyout into collapsed sidebar

**Files:**
- Modify: `frontend/src/app/components/sidebar/Sidebar.tsx`

- [ ] **Step 1: Add flyout state and import**

At the top of `Sidebar.tsx`, add the import alongside existing imports:

```tsx
import { SidebarFlyout } from './SidebarFlyout'
```

Inside the `Sidebar` function body, after the existing state declarations (around line 183, after the `toggleUnpinned` function), add:

```tsx
  const [flyoutTab, setFlyoutTab] = useState<'projects' | 'history' | null>(null)

  function toggleFlyout(tab: 'projects' | 'history') {
    setFlyoutTab((prev) => (prev === tab ? null : tab))
  }

  function openFullViewFromFlyout(tab: 'projects' | 'history') {
    setFlyoutTab(null)
    onOpenModal(tab)
  }
```

- [ ] **Step 2: Replace Projects/History icon handlers in collapsed mode**

In the collapsed mode section, find the Projects IconBtn (currently `onClick={() => onOpenModal('projects')}`) and replace with:

```tsx
        {/* Projects */}
        <IconBtn
          icon="🔭"
          onClick={() => toggleFlyout('projects')}
          title="Projects"
          isActive={isTabActive('projects') || flyoutTab === 'projects'}
        />

        {/* History */}
        <IconBtn
          icon="📖"
          onClick={() => toggleFlyout('history')}
          title="History"
          isActive={isTabActive('history') || flyoutTab === 'history'}
        />
```

- [ ] **Step 3: Render the flyout panel inside the collapsed aside**

At the end of the collapsed `<aside>` element (just before its closing `</aside>` tag), add the flyout rendering:

```tsx
        {/* Flyout panels */}
        {flyoutTab === 'history' && (
          <SidebarFlyout
            title="History"
            onClose={() => setFlyoutTab(null)}
            onOpenFullView={() => openFullViewFromFlyout('history')}
          >
            <div className="mt-0.5 pb-2">
              {pinnedSessions.length > 0 && (
                <>
                  <div className="px-3 py-1.5 text-[10px] uppercase tracking-wider text-white/25">Pinned</div>
                  {pinnedSessions.map((s) => {
                    const persona = personas.find((p) => p.id === s.persona_id)
                    return (
                      <button
                        key={s.id}
                        type="button"
                        onClick={() => { handleSessionClick(s.id, s.persona_id); setFlyoutTab(null) }}
                        className={`mx-2 mb-0.5 flex w-[calc(100%-16px)] flex-col rounded-md px-2.5 py-2 text-left transition-colors ${
                          s.id === activeSessionId ? 'bg-white/8' : 'hover:bg-white/5'
                        }`}
                      >
                        <span className="truncate text-[12px] text-white/70">{s.title ?? 'Untitled session'}</span>
                        <span className="text-[10px] text-white/25">{persona?.name}</span>
                      </button>
                    )
                  })}
                  <div className="mx-3 my-1 h-px bg-white/4" />
                </>
              )}

              <div className="px-3 py-1.5 text-[10px] uppercase tracking-wider text-white/25">Recent</div>
              {unpinnedSessions.map((s) => {
                const persona = personas.find((p) => p.id === s.persona_id)
                return (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => { handleSessionClick(s.id, s.persona_id); setFlyoutTab(null) }}
                    className={`mx-2 mb-0.5 flex w-[calc(100%-16px)] flex-col rounded-md px-2.5 py-2 text-left transition-colors ${
                      s.id === activeSessionId ? 'bg-white/8' : 'hover:bg-white/5'
                    }`}
                  >
                    <span className="truncate text-[12px] text-white/70">{s.title ?? 'Untitled session'}</span>
                    <span className="text-[10px] text-white/25">{persona?.name}</span>
                  </button>
                )
              })}

              {sessions.length === 0 && (
                <p className="px-4 py-3 text-center text-[12px] text-white/20">No history yet</p>
              )}
            </div>
          </SidebarFlyout>
        )}

        {flyoutTab === 'projects' && (
          <SidebarFlyout
            title="Projects"
            onClose={() => setFlyoutTab(null)}
            onOpenFullView={() => openFullViewFromFlyout('projects')}
          >
            <div className="flex h-full flex-col items-center justify-center gap-3 py-8 text-white/20">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z" />
              </svg>
              <span className="text-[12px]">No projects yet</span>
            </div>
          </SidebarFlyout>
        )}
```

- [ ] **Step 4: Close flyout on sidebar collapse/expand toggle**

In the `toggleCollapsed` function (or wherever sidebar collapse state is managed), ensure the flyout closes. Find where `toggleCollapsed` is called/defined and add `setFlyoutTab(null)` to it. If `toggleCollapsed` comes from a store, add the cleanup to the collapsed sidebar's expand button onClick:

```tsx
        <button
          type="button"
          onClick={() => { setFlyoutTab(null); toggleCollapsed() }}
          title="Expand sidebar"
          ...
        >
```

- [ ] **Step 5: Build and verify**

Run: `cd frontend && pnpm run build 2>&1 | grep -E "(Sidebar|SidebarFlyout)"`
Expected: No new errors related to Sidebar or SidebarFlyout

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/components/sidebar/Sidebar.tsx frontend/src/app/components/sidebar/SidebarFlyout.tsx
git commit -m "UX-009: Add flyout panels for Projects/History in collapsed sidebar"
```

---

### Task 5: Update UX-DEBT.md

**Files:**
- Modify: `UX-DEBT.md`

- [ ] **Step 1: Mark UX-008 and UX-009 as fixed**

Add status lines to both entries:

For UX-008 (after the Fix line):
```
- **Status:** Fixed — hover-only buttons replaced with permanent inline action bar (icon + label) inside each message bubble.
```

For UX-009 (after the Fix line):
```
- **Status:** Fixed — collapsed sidebar now opens flyout panels for Projects/History instead of UserModal. "Open full view" button in flyout navigates to UserModal.
```

- [ ] **Step 2: Commit**

```bash
git add UX-DEBT.md
git commit -m "Mark UX-008 and UX-009 as fixed in UX-DEBT.md"
```
