# Mobile Viewport Height Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace every `100vh`-based viewport height with the dynamic `dvh` equivalent so Chrome-on-Android browser sessions render content above the address bar instead of behind it.

**Architecture:** Pure CSS / Tailwind-utility swap across nine occurrences in seven files. No logic, no new dependencies.

**Tech Stack:** Tailwind v4 (which already ships `min-h-dvh`, `h-dvh`, `max-h-dvh` as built-in utilities), plain CSS.

---

## File Structure

Single consolidated task (everything is search-replace and ships as one logical change). The complete list:

| File | Change |
|---|---|
| `frontend/src/index.css:52` | `100vh` → `100dvh` (one occurrence) |
| `frontend/src/app/pages/LoginPage.tsx:132,155,191,352` | `min-h-screen` → `min-h-dvh` (four occurrences) |
| `frontend/src/app/pages/RegisterPage.tsx:126` | `min-h-screen` → `min-h-dvh` (one occurrence) |
| `frontend/src/app/pages/ChangePasswordPage.tsx:124` | `min-h-screen` → `min-h-dvh` (one occurrence) |
| `frontend/src/app/pages/DeletionCompletePage.tsx:66` | `min-h-screen` → `min-h-dvh` (one occurrence) |
| `frontend/src/core/components/Sheet.tsx:124` | `lg:max-h-[calc(100vh-2rem)]` → `lg:max-h-[calc(100dvh-2rem)]` (one occurrence) |

Total: 9 occurrences across 6 files.

---

## Task 1: Replace 100vh / min-h-screen with dvh equivalents

**Files:**
- Modify: `frontend/src/index.css`
- Modify: `frontend/src/app/pages/LoginPage.tsx`
- Modify: `frontend/src/app/pages/RegisterPage.tsx`
- Modify: `frontend/src/app/pages/ChangePasswordPage.tsx`
- Modify: `frontend/src/app/pages/DeletionCompletePage.tsx`
- Modify: `frontend/src/core/components/Sheet.tsx`

- [ ] **Step 1: Confirm no other occurrences sneaked in**

```bash
cd /home/chris/workspace/chatsune
rg -n "min-h-screen|h-screen|100vh" frontend/src --glob '!*.test.*'
```

Expected output (current state, 9 lines total):

```
frontend/src/index.css:52:  height: calc(100vh / var(--ui-scale, 1));
frontend/src/app/pages/ChangePasswordPage.tsx:124:    <div className="flex min-h-screen ...
frontend/src/app/pages/DeletionCompletePage.tsx:66:    <div className="min-h-screen ...
frontend/src/app/pages/RegisterPage.tsx:126:    <div className="flex min-h-screen ...
frontend/src/core/components/Sheet.tsx:124:            'lg:h-auto lg:max-h-[calc(100vh-2rem)] lg:rounded-xl',
frontend/src/app/pages/LoginPage.tsx:132:      <div className="flex min-h-screen ...
frontend/src/app/pages/LoginPage.tsx:155:      <div className="flex min-h-screen ...
frontend/src/app/pages/LoginPage.tsx:191:    <div className="flex min-h-screen ...
frontend/src/app/pages/LoginPage.tsx:352:    <div className="flex min-h-screen ...
```

If a different number appears, STOP and report — the plan was generated against this exact list and any drift means a manual review is needed.

- [ ] **Step 2: index.css — body height**

In `frontend/src/index.css` line 52, the body block currently looks like:

```css
body {
  width: calc(100vw / var(--ui-scale, 1));
  height: calc(100vh / var(--ui-scale, 1));
  transform: scale(var(--ui-scale, 1));
  transform-origin: top left;
  overflow: hidden;
  background: var(--color-base);
  overscroll-behavior: none;
}
```

Change line 52 only — `100vh` → `100dvh`:

```css
body {
  width: calc(100vw / var(--ui-scale, 1));
  height: calc(100dvh / var(--ui-scale, 1));
  transform: scale(var(--ui-scale, 1));
  transform-origin: top left;
  overflow: hidden;
  background: var(--color-base);
  overscroll-behavior: none;
}
```

The `100vw` on line 51 stays. Horizontal viewport doesn't change with address-bar visibility, no benefit to swapping it.

- [ ] **Step 3: LoginPage.tsx — four `min-h-screen` to `min-h-dvh`**

In `frontend/src/app/pages/LoginPage.tsx` there are four occurrences of `min-h-screen` on lines 132, 155, 191, 352. The class is part of a larger Tailwind string each time, e.g.:

```tsx
<div className="flex min-h-screen items-center justify-center bg-base px-4 py-6 pb-[max(1.5rem,env(safe-area-inset-bottom))]">
```

Replace `min-h-screen` with `min-h-dvh` in all four lines. The simplest reliable approach is a global search-and-replace on this file:

```bash
sed -i 's/min-h-screen/min-h-dvh/g' frontend/src/app/pages/LoginPage.tsx
```

If you prefer to do it manually with the Edit tool, change each occurrence individually — each line's surrounding text differs slightly (different parent components), so do not use `replace_all` blindly across the whole repo.

- [ ] **Step 4: RegisterPage.tsx**

```bash
sed -i 's/min-h-screen/min-h-dvh/g' frontend/src/app/pages/RegisterPage.tsx
```

Single occurrence on line 126.

- [ ] **Step 5: ChangePasswordPage.tsx**

```bash
sed -i 's/min-h-screen/min-h-dvh/g' frontend/src/app/pages/ChangePasswordPage.tsx
```

Single occurrence on line 124.

- [ ] **Step 6: DeletionCompletePage.tsx**

```bash
sed -i 's/min-h-screen/min-h-dvh/g' frontend/src/app/pages/DeletionCompletePage.tsx
```

Single occurrence on line 66.

- [ ] **Step 7: Sheet.tsx — arbitrary-value calc**

In `frontend/src/core/components/Sheet.tsx` line 124, the current class is:

```tsx
'lg:h-auto lg:max-h-[calc(100vh-2rem)] lg:rounded-xl',
```

Change to:

```tsx
'lg:h-auto lg:max-h-[calc(100dvh-2rem)] lg:rounded-xl',
```

The `lg:` prefix means this only applies on large viewports (desktop). On mobile, the Sheet uses different sizing (the `lg:` overrides don't apply), so this is mostly a consistency fix — but desktop mobile-emulators and narrow desktop windows benefit too.

- [ ] **Step 8: Verify all replacements landed**

```bash
cd /home/chris/workspace/chatsune
rg -n "min-h-screen|h-screen|100vh" frontend/src --glob '!*.test.*'
```

Expected: empty output (zero matches). If any remain, locate and replace them following the same pattern.

Also verify the `dvh` versions are now in place:

```bash
rg -n "min-h-dvh|100dvh" frontend/src --glob '!*.test.*' | wc -l
```

Expected: 9.

- [ ] **Step 9: Build**

```bash
cd /home/chris/workspace/chatsune/frontend
pnpm run build
```

Expected: clean build (`tsc -b` and Vite). No new warnings or errors.

If Tailwind warns about an unknown class (`min-h-dvh`), check the Tailwind version:

```bash
grep '"tailwindcss"' frontend/package.json
```

Expected: `"^4.2.2"` or higher (Tailwind v4). v4 ships `*-dvh` utilities by default. If the version is somehow lower, STOP and report — the spec assumed Tailwind v4 and we'd need a different approach.

- [ ] **Step 10: Manual verification (the product owner runs this)**

The Pixel Tablet behaviour cannot be verified from the developer host — it requires the actual device. The product owner runs the spec's manual-verification scenarios:

**Pixel Tablet, Chrome browser (the original bug):**
1. Open Chatsune in Chrome on the Pixel Tablet.
2. Open the sidebar drawer.
3. Expected: all sidebar items visible above the address bar, no clipping.
4. Navigate to the personas page.
5. Expected: the bottom-most persona card is fully visible, not clipped.
6. Scroll up/down to toggle the address bar.
7. Expected: layout adjusts smoothly; nothing trapped behind the address bar in either state.

**PWA (regression check):**
8. Open Chatsune as PWA.
9. Expected: layout looks identical to before, no extra space at the bottom.

**Login flow (regression check):**
10. Logout, land on the login page on Pixel Tablet in browser.
11. Expected: login form is centred vertically in the visible area.

**Galaxy S20 Ultra (regression check):**
12. Open Chatsune in Chrome on S20 Ultra.
13. Expected: behaviour identical to before, sidebar fits, no new artefacts.

If any scenario fails, do NOT commit. Report which step and what was observed.

- [ ] **Step 11: Commit**

After manual verification passes:

```bash
cd /home/chris/workspace/chatsune
git add frontend/src/index.css \
        frontend/src/app/pages/LoginPage.tsx \
        frontend/src/app/pages/RegisterPage.tsx \
        frontend/src/app/pages/ChangePasswordPage.tsx \
        frontend/src/app/pages/DeletionCompletePage.tsx \
        frontend/src/core/components/Sheet.tsx
git commit -m "Use dvh for viewport heights so mobile address bar stops clipping content"
```

---

## Constraints

- Do NOT touch any file outside the six listed.
- Do NOT replace `100vw` with `100dvw` — horizontal viewport doesn't change with address-bar visibility, no benefit.
- Do NOT add unit tests — pure CSS / Tailwind-class change, verified via the device-specific manual scenarios.
- Do NOT push, merge, branch-switch, or amend prior commits.
- Frontend build check: `pnpm run build` (which runs `tsc -b`), not `pnpm tsc --noEmit`.
