# Low-Effort UX Batch — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix four low-effort UX items: event-driven GEN button feedback, outside-click delete confirmation, CTX label on context pill, and mark UX-015 as fixed.

**Architecture:** Four independent frontend-only changes. GEN button uses `useEffect` on `session.title` prop to detect when the title arrives. Delete confirmation replaces timer with document mousedown listener. Context pill always shows "CTX" label. UX-015 is already fixed (button only rendered when model supports reasoning).

**Tech Stack:** React, TypeScript, Tailwind CSS

**Spec:** `docs/superpowers/specs/2026-04-06-ux-batch-low-effort-design.md`

---

### Task 1: UX-010 — Event-driven GEN button (UserModal HistoryTab)

**Files:**
- Modify: `frontend/src/app/components/user-modal/HistoryTab.tsx`

The `SessionRow` sub-component inside this file receives `session` as a prop. When a title is generated, the parent re-renders with an updated `session.title`. We detect this change to reset the GEN button.

- [ ] **Step 1: Replace the hardcoded 2s timeout with title-change detection**

Find the `handleGenerateTitle` function (lines 229-239). Replace it with:

```typescript
  const handleGenerateTitle = useCallback(async () => {
    setGenerating(true)
    try {
      await chatApi.generateTitle(session.id)
    } catch {
      // Title arrives via event
    }
  }, [session.id])
```

Note: removed the `finally` block with `setTimeout`. The button stays in "..." state until the title changes.

- [ ] **Step 2: Add a useEffect to detect title changes and show "OK"**

Add a new state and effect. Find the existing state declarations (around line 185, `const [generating, setGenerating] = useState(false)`). Add after it:

```typescript
  const [genSuccess, setGenSuccess] = useState(false)
```

Then add a `useEffect` after the existing effects (after line 198):

```typescript
  // Reset GEN button when title arrives
  useEffect(() => {
    if (!generating) return
    setGenerating(false)
    setGenSuccess(true)
    const t = setTimeout(() => setGenSuccess(false), 1000)
    return () => clearTimeout(t)
  }, [session.title])

  // Fallback: reset after 10s if no title event arrives
  useEffect(() => {
    if (!generating) return
    const t = setTimeout(() => setGenerating(false), 10000)
    return () => clearTimeout(t)
  }, [generating])
```

- [ ] **Step 3: Update the GEN button text**

Find the GEN button (lines 317-325). Replace:

```typescript
            {generating ? '...' : 'GEN'}
```

with:

```typescript
            {generating ? '...' : genSuccess ? 'OK' : 'GEN'}
```

Also update the className to show gold colour on success:

```typescript
            className={`${BTN_NEUTRAL} ${generating ? 'opacity-30 cursor-not-allowed' : ''} ${genSuccess ? 'text-gold' : ''}`}
```

- [ ] **Step 4: Verify**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit`
Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/user-modal/HistoryTab.tsx
git commit -m "UX-010: Event-driven GEN button feedback in UserModal HistoryTab"
```

---

### Task 2: UX-010 — Event-driven GEN button (PersonaOverlay HistoryTab)

**Files:**
- Modify: `frontend/src/app/components/persona-overlay/HistoryTab.tsx`

Same changes as Task 1 but in the persona overlay variant.

- [ ] **Step 1: Replace the hardcoded 2s timeout with title-change detection**

Find the `handleGenerateTitle` function (lines 175-184). Replace it with:

```typescript
  const handleGenerateTitle = useCallback(async () => {
    setGenerating(true)
    try {
      await chatApi.generateTitle(session.id)
    } catch {
      // Title arrives via event
    }
  }, [session.id])
```

- [ ] **Step 2: Add state and effects for title-change detection**

Find the existing state declarations (around the `const [generating, setGenerating] = useState(false)` line). Add after it:

```typescript
  const [genSuccess, setGenSuccess] = useState(false)
```

Then add the same two effects as Task 1, after the existing effects:

```typescript
  // Reset GEN button when title arrives
  useEffect(() => {
    if (!generating) return
    setGenerating(false)
    setGenSuccess(true)
    const t = setTimeout(() => setGenSuccess(false), 1000)
    return () => clearTimeout(t)
  }, [session.title])

  // Fallback: reset after 10s if no title event arrives
  useEffect(() => {
    if (!generating) return
    const t = setTimeout(() => setGenerating(false), 10000)
    return () => clearTimeout(t)
  }, [generating])
```

- [ ] **Step 3: Update the GEN button text**

Find the GEN button (lines 239-247). Replace:

```typescript
            {generating ? '...' : 'GEN'}
```

with:

```typescript
            {generating ? '...' : genSuccess ? 'OK' : 'GEN'}
```

Also update the className:

```typescript
            className={`${BTN_NEUTRAL} ${generating ? 'opacity-30 cursor-not-allowed' : ''} ${genSuccess ? 'text-gold' : ''}`}
```

- [ ] **Step 4: Verify**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit`
Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/persona-overlay/HistoryTab.tsx
git commit -m "UX-010: Event-driven GEN button feedback in PersonaOverlay HistoryTab"
```

---

### Task 3: UX-011 — Outside-click delete confirmation (UserModal HistoryTab)

**Files:**
- Modify: `frontend/src/app/components/user-modal/HistoryTab.tsx`

- [ ] **Step 1: Replace timer with outside-click handler**

Find the `startDeleteConfirm` function (lines 250-254). Replace it with:

```typescript
  const startDeleteConfirm = useCallback(() => {
    setConfirmDelete(true)
  }, [])
```

- [ ] **Step 2: Add a ref for the SURE? button and outside-click effect**

Add a ref near the other refs (around line 187):

```typescript
  const sureRef = useRef<HTMLButtonElement>(null)
```

Replace the existing cleanup effect (lines 194-198) with an outside-click effect:

```typescript
  // Dismiss delete confirmation on outside click
  useEffect(() => {
    if (!confirmDelete) return
    const handleMouseDown = (e: MouseEvent) => {
      if (sureRef.current && !sureRef.current.contains(e.target as Node)) {
        setConfirmDelete(false)
      }
    }
    document.addEventListener('mousedown', handleMouseDown)
    return () => document.removeEventListener('mousedown', handleMouseDown)
  }, [confirmDelete])
```

- [ ] **Step 3: Remove the deleteTimer ref**

Remove the line (around line 187):

```typescript
  const deleteTimer = useRef<ReturnType<typeof setTimeout>>()
```

- [ ] **Step 4: Add ref to the SURE? button**

Find the SURE? button (around line 327):

```typescript
            <button type="button" onClick={handleDelete} className={BTN_RED}>
```

Add the ref:

```typescript
            <button ref={sureRef} type="button" onClick={handleDelete} className={BTN_RED}>
```

- [ ] **Step 5: Verify**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit`
Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/components/user-modal/HistoryTab.tsx
git commit -m "UX-011: Replace delete confirmation timer with outside-click in UserModal HistoryTab"
```

---

### Task 4: UX-011 — Outside-click delete confirmation (BookmarksTab)

**Files:**
- Modify: `frontend/src/app/components/user-modal/BookmarksTab.tsx`

Same pattern as Task 3.

- [ ] **Step 1: Replace timer with outside-click handler**

Find the `startDeleteConfirm` function (lines 279-283). Replace it with:

```typescript
  const startDeleteConfirm = useCallback(() => {
    setConfirmDelete(true)
  }, [])
```

- [ ] **Step 2: Add ref and outside-click effect**

Add a ref near the other refs:

```typescript
  const sureRef = useRef<HTMLButtonElement>(null)
```

Find and replace the existing cleanup effect for the delete timer with:

```typescript
  // Dismiss delete confirmation on outside click
  useEffect(() => {
    if (!confirmDelete) return
    const handleMouseDown = (e: MouseEvent) => {
      if (sureRef.current && !sureRef.current.contains(e.target as Node)) {
        setConfirmDelete(false)
      }
    }
    document.addEventListener('mousedown', handleMouseDown)
    return () => document.removeEventListener('mousedown', handleMouseDown)
  }, [confirmDelete])
```

- [ ] **Step 3: Remove the deleteTimer ref**

Remove the `deleteTimer` ref declaration.

- [ ] **Step 4: Add ref to the SURE? button**

Find the SURE? button (around line 349):

```typescript
            <button type="button" onClick={handleDelete} className={BTN_RED}>
```

Add the ref:

```typescript
            <button ref={sureRef} type="button" onClick={handleDelete} className={BTN_RED}>
```

- [ ] **Step 5: Verify**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit`
Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/components/user-modal/BookmarksTab.tsx
git commit -m "UX-011: Replace delete confirmation timer with outside-click in BookmarksTab"
```

---

### Task 5: UX-014 — Show "CTX" label in ContextStatusPill

**Files:**
- Modify: `frontend/src/features/chat/ContextStatusPill.tsx`

- [ ] **Step 1: Always show label text**

Replace the entire component function (lines 16-29) with:

```typescript
export function ContextStatusPill({ status, fillPercentage }: ContextStatusPillProps) {
  const pct = Math.round(fillPercentage * 100)

  return (
    <span
      className={`flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-[11px] ${BORDER_COLOURS[status]} bg-white/3 text-white/40`}
      title={`Context window: ${pct}% used`}
    >
      <span data-testid="context-dot" className={`h-1.5 w-1.5 rounded-full ${DOT_COLOURS[status]}`} />
      <span>{status === 'green' ? 'CTX' : `CTX ${pct}%`}</span>
    </span>
  )
}
```

- [ ] **Step 2: Verify**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit`
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/chat/ContextStatusPill.tsx
git commit -m "UX-014: Always show CTX label in ContextStatusPill"
```

---

### Task 6: Mark UX-015 as already fixed in UX-DEBT.md

**Files:**
- Modify: `UX-DEBT.md`

- [ ] **Step 1: Add ALREADY FIXED status to UX-015**

Find the UX-015 heading (around line 147). Change:

```markdown
**[UX-015] Reasoning toggle: no visual difference between "not supported" and "manually off"**
```

to:

```markdown
**[UX-015] Reasoning toggle: no visual difference between "not supported" and "manually off"** — ALREADY FIXED
```

And add at the end of the UX-015 section (before the next `---`):

```markdown
- **Status:** Already fixed — the reasoning button is only rendered when `modelSupportsReasoning` is true. When the model doesn't support reasoning, the button is not shown at all.
```

- [ ] **Step 2: Commit**

```bash
git add UX-DEBT.md
git commit -m "Mark UX-015 as already fixed in UX-DEBT.md"
```
