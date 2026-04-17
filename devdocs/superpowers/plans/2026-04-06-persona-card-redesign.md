# PersonaCard Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign PersonaCard to replace invisible split click zones with a single Continue click target, add SVG icon menu bar with New button, and display model name.

**Architecture:** All changes are in one file (`PersonaCard.tsx`). We remove the invisible overlay zones and `hoveredZone` state, make the card body clickable for Continue, replace text menu buttons with SVG icons, add a 4th "New Chat" button, and add model name display below the tagline.

**Tech Stack:** React, TypeScript, Tailwind CSS, inline SVGs

**Spec:** `docs/superpowers/specs/2026-04-06-persona-card-redesign-design.md`

---

### Task 1: Remove invisible click zones, make card body clickable

**Files:**
- Modify: `frontend/src/app/components/persona-card/PersonaCard.tsx`

- [ ] **Step 1: Remove the `hoveredZone` state**

Find and remove line 27:

```typescript
  const [hoveredZone, setHoveredZone] = useState<"continue" | "new" | null>(null);
```

- [ ] **Step 2: Remove the invisible click zones overlay**

Remove the entire block from line 190 to line 245 (the `{/* Chat zones — absolute overlay above menu bar */}` div with both click zone buttons and the divider).

- [ ] **Step 3: Make the card body area clickable for Continue**

The card content area (lines 131-188, the CSS Grid div with name/avatar/tagline) needs to become clickable. Wrap it in a button or add click handling. Replace the opening tag of the grid div (lines 132-137):

```typescript
      {/* Card content — clickable for Continue */}
      <button
        type="button"
        className="flex-1 grid items-center justify-items-center px-3 bg-transparent border-none cursor-pointer w-full"
        style={{
          gridTemplateRows: "auto 1fr auto",
          paddingBottom: "28px",
        }}
        onPointerDown={(e) => e.stopPropagation()}
        onClick={() => onContinue(persona.id)}
      >
```

And change the closing `</div>` at line 188 to `</button>`.

- [ ] **Step 4: Add a hover hint "▸ Continue" above the menu bar**

Add inside the card body button, after the tagline paragraph (after line 187), before the closing `</button>`:

```tsx
        {/* Continue hint — visible on hover */}
        <span
          className="text-[9px] font-semibold uppercase tracking-[1.5px] transition-opacity duration-200 self-end"
          style={{
            color: chakra.hex + "80",
            opacity: isHovered ? 1 : 0,
          }}
        >
          ▸ Continue
        </span>
```

Note: Adjust the `gridTemplateRows` to `"auto 1fr auto auto"` to accommodate the new row.

Update the style:

```typescript
        style={{
          gridTemplateRows: "auto 1fr auto auto",
          paddingBottom: "28px",
        }}
```

- [ ] **Step 5: Remove the unused hoveredZone from onMouseLeave**

Find the `onMouseLeave` handler on the outer div (lines 70-73). Change from:

```typescript
      onMouseLeave={() => {
        setIsHovered(false);
        setHoveredZone(null);
      }}
```

to:

```typescript
      onMouseLeave={() => setIsHovered(false)}
```

- [ ] **Step 6: Verify**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit`
Expected: No errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/app/components/persona-card/PersonaCard.tsx
git commit -m "Replace invisible click zones with single Continue click target"
```

---

### Task 2: Replace text menu bar with SVG icons + New button

**Files:**
- Modify: `frontend/src/app/components/persona-card/PersonaCard.tsx`

- [ ] **Step 1: Replace the menuButtons array and menu bar rendering**

Find the `menuButtons` array (lines 58-62):

```typescript
  const menuButtons: { label: string; tab: PersonaOverlayTab }[] = [
    { label: "Overview", tab: "overview" },
    { label: "Edit", tab: "edit" },
    { label: "History", tab: "history" },
  ];
```

Replace it with:

```typescript
  const menuButtons: { title: string; tab: PersonaOverlayTab; icon: React.ReactNode }[] = [
    {
      title: "Overview",
      tab: "overview",
      icon: (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <path d="M12 16v-4" />
          <path d="M12 8h.01" />
        </svg>
      ),
    },
    {
      title: "Edit",
      tab: "edit",
      icon: (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
          <path d="m15 5 4 4" />
        </svg>
      ),
    },
    {
      title: "History",
      tab: "history",
      icon: (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <polyline points="12 6 12 12 16 14" />
        </svg>
      ),
    },
  ];
```

- [ ] **Step 2: Replace the menu bar rendering**

Find the menu bar div (lines 247-276). Replace the entire block with:

```tsx
      {/* Menu bar — bottom */}
      <div
        className="flex h-12 relative z-[3]"
        style={{ borderTop: `1px solid rgba(255,255,255,0.06)` }}
      >
        {menuButtons.map((btn, i) => (
          <button
            key={btn.tab}
            className="flex-1 flex items-center justify-center transition-colors duration-200 bg-transparent border-none cursor-pointer"
            style={{
              color: "rgba(255,255,255,0.35)",
              borderRight: "1px solid rgba(255,255,255,0.04)",
            }}
            title={btn.title}
            onPointerDown={(e) => e.stopPropagation()}
            onClick={() => onOpenOverlay(persona.id, btn.tab)}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = chakra.hex;
              e.currentTarget.style.background = chakra.hex + "0f";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = "rgba(255,255,255,0.35)";
              e.currentTarget.style.background = "transparent";
            }}
          >
            {btn.icon}
          </button>
        ))}

        {/* New Chat button */}
        <button
          className="flex-1 flex items-center justify-center transition-colors duration-200 bg-transparent border-none cursor-pointer"
          style={{ color: chakra.hex + "b3" }}
          title="New Chat"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={() => onNewChat(persona.id)}
          onMouseEnter={(e) => {
            e.currentTarget.style.color = chakra.hex;
            e.currentTarget.style.background = chakra.hex + "0f";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.color = chakra.hex + "b3";
            e.currentTarget.style.background = "transparent";
          }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M5 12h14" />
            <path d="M12 5v14" />
          </svg>
        </button>
      </div>
```

- [ ] **Step 3: Verify**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit`
Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/persona-card/PersonaCard.tsx
git commit -m "Replace text menu bar with SVG icon buttons and add New Chat button"
```

---

### Task 3: Add model name display

**Files:**
- Modify: `frontend/src/app/components/persona-card/PersonaCard.tsx`

- [ ] **Step 1: Add model name below the tagline**

Find the tagline paragraph inside the card body button. After the tagline `</p>` (the one with `{persona.tagline}`), add:

```tsx
        {/* Model name */}
        <p
          className="font-mono text-[9px] text-center self-end w-full"
          style={{
            color: chakra.hex + "4d",
            letterSpacing: "0.5px",
          }}
        >
          {persona.model_unique_id.split(":").slice(1).join(":")}
        </p>
```

Note: The grid now has 5 rows (name, avatar, tagline, continue-hint, model). Update `gridTemplateRows` to `"auto 1fr auto auto auto"`.

Actually, reconsider the order. The model should be between tagline and continue-hint:

1. Name (top)
2. Avatar (center, flex)
3. Tagline
4. Model name
5. Continue hint

Update `gridTemplateRows` to `"auto 1fr auto auto auto"`.

- [ ] **Step 2: Verify**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit`
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/components/persona-card/PersonaCard.tsx
git commit -m "Show model name on PersonaCard below tagline (UX-006)"
```

---

### Task 4: Update UX-DEBT.md

**Files:**
- Modify: `UX-DEBT.md`

- [ ] **Step 1: Mark UX-006 as fixed**

Find the UX-006 heading:

```markdown
**[UX-006] PersonaCard has invisible click zones -- no visual hint for "Continue" vs. "New"**
```

Change it to:

```markdown
**[UX-006] PersonaCard has invisible click zones -- no visual hint for "Continue" vs. "New"** — FIXED
```

Add at the end of the UX-006 section:

```markdown
- **Status:** Fixed — entire card body is now a single "Continue" click target with hover hint. "New Chat" is an explicit icon button in the menu bar. Menu bar uses SVG icons instead of text. Model name displayed below tagline.
```

- [ ] **Step 2: Commit**

```bash
git add UX-DEBT.md
git commit -m "Mark UX-006 as fixed in UX-DEBT.md"
```
