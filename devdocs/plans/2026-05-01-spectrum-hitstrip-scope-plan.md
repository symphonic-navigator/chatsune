# Spectrum HitStrip Scope — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move `VoiceVisualiserHitStrip` from the global fixed layer into `<main>` so its click area no longer extends over the sidebar (desktop) or drawer/backdrop (mobile).

**Architecture:** Single component move + style change. The HitStrip becomes a child of `<main>` (which is already `position: relative`) and switches from `position: fixed` to `position: absolute`. No changes to canvas, countdown pie, renderer, or layout store. Drawer aussparen on mobile is automatic via existing z-index layering (drawer `z-40`, backdrop `z-30`, both above `<main>`).

**Tech Stack:** React + TSX, no test framework needed (visual layout change verified manually).

---

## File Structure

- **Modify:** `frontend/src/features/voice/components/VoiceVisualiserHitStrip.tsx`
  — change one inline-style key (`position`).
- **Modify:** `frontend/src/app/layouts/AppLayout.tsx`
  — move `<VoiceVisualiserHitStrip />` from global-layer siblings (line 353) into `<main>` (after the persona overlay block, before the `</main>` close on line 349).

No new files. No test files (no logic to unit-test; verification is visual / interaction-based per the spec's Manual Verification section).

---

## Task 1: Move HitStrip into `<main>` and switch to absolute positioning

**Files:**
- Modify: `frontend/src/features/voice/components/VoiceVisualiserHitStrip.tsx:46`
- Modify: `frontend/src/app/layouts/AppLayout.tsx:312-356`

- [ ] **Step 1: Change HitStrip from fixed to absolute**

In `frontend/src/features/voice/components/VoiceVisualiserHitStrip.tsx`, change the `position` value in the inline style object on line 46 from `'fixed'` to `'absolute'`. All other style keys remain unchanged.

Replace:

```tsx
        style={{
          position: 'fixed',
          left: 0,
          width: '100%',
          top: '35%',
          height: '30%',
          background: 'transparent',
          border: 0,
          padding: 0,
          margin: 0,
          cursor: 'pointer',
          zIndex: 2,
          touchAction: 'manipulation',
        }}
```

with:

```tsx
        style={{
          position: 'absolute',
          left: 0,
          width: '100%',
          top: '35%',
          height: '30%',
          background: 'transparent',
          border: 0,
          padding: 0,
          margin: 0,
          cursor: 'pointer',
          zIndex: 2,
          touchAction: 'manipulation',
        }}
```

- [ ] **Step 2: Move `<VoiceVisualiserHitStrip />` into `<main>`**

In `frontend/src/app/layouts/AppLayout.tsx`:

(a) Remove the line `<VoiceVisualiserHitStrip />` from line 353 (the global-layer sibling block at the end of the layout).

(b) Add `<VoiceVisualiserHitStrip />` as the last child inside `<main>`, after the `personaOverlay` conditional block and before `</main>`.

Concretely, the `<main>` block currently ends like this (lines 336-349):

```tsx
          {personaOverlay && (
            <PersonaOverlay
              persona={overlayPersona}
              allPersonas={allPersonas}
              isCreating={personaOverlay.personaId === null}
              activeTab={personaOverlay.tab}
              onClose={closePersonaOverlay}
              onTabChange={handlePersonaOverlayTabChange}
              onSave={handlePersonaSave}
              onNavigate={(path) => navigate(path)}
              sessions={filteredSessions}
            />
          )}
        </main>
```

Change it to:

```tsx
          {personaOverlay && (
            <PersonaOverlay
              persona={overlayPersona}
              allPersonas={allPersonas}
              isCreating={personaOverlay.personaId === null}
              activeTab={personaOverlay.tab}
              onClose={closePersonaOverlay}
              onTabChange={handlePersonaOverlayTabChange}
              onSave={handlePersonaSave}
              onNavigate={(path) => navigate(path)}
              sessions={filteredSessions}
            />
          )}
          <VoiceVisualiserHitStrip />
        </main>
```

And the global-layer block currently looks like this (lines 351-356):

```tsx
      <VoiceVisualiser personaColourHex={activePersonaHex} />
      <VoiceCountdownPie personaColourHex={activePersonaHex} />
      <VoiceVisualiserHitStrip />
      <ToastContainer />
      <MobileToastContainer />
      <InstallHint />
```

Change it to:

```tsx
      <VoiceVisualiser personaColourHex={activePersonaHex} />
      <VoiceCountdownPie personaColourHex={activePersonaHex} />
      <ToastContainer />
      <MobileToastContainer />
      <InstallHint />
```

The existing `import { VoiceVisualiserHitStrip }` at the top of the file stays — it is still referenced, just from inside `<main>` now.

- [ ] **Step 3: Run frontend build**

Run from the `frontend/` directory:

```bash
pnpm run build
```

Expected: build succeeds with no TypeScript errors. (`tsc -b` runs as part of `pnpm run build` and is the stricter check per project convention — `pnpm tsc --noEmit` alone is not sufficient.)

If the build fails, read the error, fix it, and re-run. Common cause: stale import that needs adjusting (should not happen here — the import already exists).

- [ ] **Step 4: Manual verification on a real browser**

The product owner will run these steps. Do not skip — visual / interaction changes cannot be fully verified by build success alone.

Start the dev server (`pnpm run dev` in `frontend/`) or use a deployed build, then:

**Desktop (lg+ viewport, ≥ 1024px wide):**

1. Start a voice session so the spectrum is active.
2. Click on a sidebar item (e.g. a chat session row).
   Expected: sidebar action runs, voice does NOT pause.
3. Click on the spectrum area in the centre.
   Expected: voice pauses.
4. Click on the spectrum area again.
   Expected: voice resumes.

**Mobile (drawer closed, < 1024px wide):**

5. Start a voice session.
6. Click in the centre content area where the spectrum is visible.
   Expected: voice pauses.
7. Click again to resume.
   Expected: voice resumes.

**Mobile (drawer open):**

8. Start a voice session.
9. Open the sidebar drawer (hamburger).
10. Click on a sidebar item inside the drawer.
    Expected: sidebar action runs, voice does NOT pause.
11. Click on the dark backdrop area to the right of the drawer.
    Expected: drawer closes, voice does NOT pause.

**Regression checks:**

12. With drawer closed and voice paused, click on the spectrum area to confirm resume still works.
13. Confirm the spectrum bars themselves still render in the main content column with no visual change.

If any of these fail, do NOT commit — report the failure to the product owner.

- [ ] **Step 5: Commit**

Stage only the two changed files and commit. Imperative free-form message per project convention; no Conventional Commits prefix.

```bash
git add frontend/src/features/voice/components/VoiceVisualiserHitStrip.tsx \
        frontend/src/app/layouts/AppLayout.tsx
git commit -m "Scope spectrum HitStrip to main content area"
```

Do NOT merge to master, do NOT push, do NOT switch branches. The product owner handles integration.

---

## Out of scope

- Refactoring `VoiceVisualiser` (canvas) or `VoiceCountdownPie` into the same container — their renderer logic already clips to chatview bounds.
- Adding a CSS variable for sidebar width — YAGNI; HitStrip now follows `<main>` automatically.
- State tracking of mobile drawer-open state — handled by existing z-index layering.
