# Persona Card Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign persona cards with new layout (name/avatar/tagline), split click zones for Continue/New chat, dedicated drag handle, bottom menu bar opening the overlay, and least-used colour suggestion on creation.

**Architecture:** Rewrite `PersonaCard.tsx` with CSS Grid layout and absolute-positioned chat zones. Update `PersonasPage.tsx` to pass overlay-opening callbacks per tab. Add a `suggestColour` utility and wire it into `PersonaOverlay.tsx` for new persona defaults.

**Tech Stack:** React, TypeScript, @dnd-kit/sortable, Tailwind CSS

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `frontend/src/core/utils/suggestColour.ts` | Least-used colour selection algorithm |
| Rewrite | `frontend/src/app/components/persona-card/PersonaCard.tsx` | New card layout, zones, menu bar |
| Modify | `frontend/src/app/pages/PersonasPage.tsx` | New handler signatures, overlay tab routing |
| Modify | `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx` | Use `suggestColour` for default persona |

---

### Task 1: Least-Used Colour Suggestion Utility

**Files:**
- Create: `frontend/src/core/utils/suggestColour.ts`

- [ ] **Step 1: Create the utility**

```ts
import type { ChakraColour } from "../types/chakra";

const ALL_COLOURS: ChakraColour[] = [
  "root", "sacral", "solar", "heart", "throat", "third_eye", "crown",
];

/**
 * Pick a random colour from those with the lowest usage count.
 * If no personas exist, picks from all colours equally.
 */
export function suggestColour(existingSchemes: ChakraColour[]): ChakraColour {
  const counts = new Map<ChakraColour, number>(
    ALL_COLOURS.map((c) => [c, 0]),
  );
  for (const scheme of existingSchemes) {
    counts.set(scheme, (counts.get(scheme) ?? 0) + 1);
  }
  const minCount = Math.min(...counts.values());
  const leastUsed = ALL_COLOURS.filter((c) => counts.get(c) === minCount);
  return leastUsed[Math.floor(Math.random() * leastUsed.length)];
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/core/utils/suggestColour.ts
git commit -m "Add least-used colour suggestion utility for persona creation"
```

---

### Task 2: Rewrite PersonaCard Component

**Files:**
- Rewrite: `frontend/src/app/components/persona-card/PersonaCard.tsx`

- [ ] **Step 1: Rewrite PersonaCard with new layout and interactions**

The new component changes:
- Props: replace `onContinue`/`onNewChat`/`onOpenOverlay` with `onContinue`/`onNewChat`/`onOpenOverlay(personaId, tab)`
- Layout: CSS Grid with `grid-template-rows: auto 1fr auto` for fixed avatar positioning
- Drag handle: only the grip icon (top-left) gets `{...listeners}`, not the entire card
- Chat zones: absolute overlay with 2/3 | 1/3 split, ghost labels that glow on zone hover
- Menu bar: Overview/Edit/History buttons at bottom

```tsx
import { useState } from "react";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { PersonaDto } from "../../../core/types/persona";
import type { PersonaOverlayTab } from "../persona-overlay/PersonaOverlay";
import { CHAKRA_PALETTE } from "../../../core/types/chakra";

interface PersonaCardProps {
  persona: PersonaDto;
  index: number;
  onContinue: (personaId: string) => void;
  onNewChat: (personaId: string) => void;
  onOpenOverlay: (personaId: string, tab: PersonaOverlayTab) => void;
}

export default function PersonaCard({
  persona,
  index,
  onContinue,
  onNewChat,
  onOpenOverlay,
}: PersonaCardProps) {
  const [isHovered, setIsHovered] = useState(false);
  const [hoveredZone, setHoveredZone] = useState<"continue" | "new" | null>(null);

  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: persona.id });

  const chakra = CHAKRA_PALETTE[persona.colour_scheme];

  const glowStrength = isHovered
    ? chakra.glow.replace("0.3", "0.55")
    : chakra.glow;

  const cardStyle: React.CSSProperties = {
    width: "clamp(160px, 42vw, 210px)",
    height: "clamp(240px, 63vw, 320px)",
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
    background: `linear-gradient(160deg, #1a1528 0%, #0f0d16 100%)`,
    border: `1px solid ${isHovered ? chakra.hex + "55" : chakra.hex + "28"}`,
    boxShadow: isHovered
      ? `0 0 24px ${glowStrength}, 0 0 8px ${glowStrength}, inset 0 1px 0 rgba(255,255,255,0.06)`
      : `0 0 12px ${glowStrength}, inset 0 1px 0 rgba(255,255,255,0.04)`,
    animation: `card-entrance 0.6s cubic-bezier(0.16, 1, 0.3, 1) ${index * 0.1}s both`,
  };

  const menuButtons: { label: string; tab: PersonaOverlayTab }[] = [
    { label: "Overview", tab: "overview" },
    { label: "Edit", tab: "edit" },
    { label: "History", tab: "history" },
  ];

  return (
    <div
      ref={setNodeRef}
      style={cardStyle}
      className="relative flex flex-col rounded-xl overflow-hidden select-none"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => {
        setIsHovered(false);
        setHoveredZone(null);
      }}
      {...attributes}
    >
      {/* Chakra gradient overlay */}
      <div
        className="absolute inset-x-0 top-0 h-1/2 pointer-events-none"
        style={{ background: chakra.gradient }}
      />

      {/* Drag handle — only this element triggers drag */}
      <div
        className="absolute top-2.5 left-2.5 z-10 flex flex-col gap-[3px] cursor-grab active:cursor-grabbing p-1"
        {...listeners}
      >
        {[0, 1, 2].map((row) => (
          <div key={row} className="flex gap-[3px]">
            <div
              className="w-[3px] h-[3px] rounded-full"
              style={{ background: "rgba(255,255,255,0.3)" }}
            />
            <div
              className="w-[3px] h-[3px] rounded-full"
              style={{ background: "rgba(255,255,255,0.3)" }}
            />
          </div>
        ))}
      </div>

      {/* NSFW indicator */}
      {persona.nsfw && (
        <div className="absolute top-2 right-2 z-10 text-xs leading-none">
          💋
        </div>
      )}

      {/* Card content — CSS Grid: name / avatar / tagline */}
      <div
        className="flex-1 grid items-center justify-items-center px-3"
        style={{
          gridTemplateRows: "auto 1fr auto",
          paddingBottom: "28px", /* space for zone labels */
        }}
      >
        {/* Name */}
        <p
          className="font-serif text-[15px] font-semibold leading-tight pt-4 self-start"
          style={{ color: "#e8e0d4" }}
        >
          {persona.name}
        </p>

        {/* Avatar / Monogram */}
        <div
          className="w-[90px] h-[90px] rounded-full flex items-center justify-center self-center overflow-hidden"
          style={{
            background: `radial-gradient(circle at center, ${chakra.hex}33 0%, ${chakra.hex}11 50%, transparent 70%)`,
            boxShadow: `0 0 20px ${glowStrength}, 0 0 40px ${chakra.hex}22`,
            border: `2px solid ${chakra.hex}4d`,
          }}
        >
          {persona.profile_image ? (
            <img
              src={persona.profile_image}
              alt={persona.name}
              className="w-full h-full object-cover rounded-full"
            />
          ) : (
            <span
              className="font-serif text-3xl font-semibold"
              style={{ color: chakra.hex }}
            >
              {persona.monogram}
            </span>
          )}
        </div>

        {/* Tagline — anchored at bottom, max 2 lines with ellipsis */}
        <p
          className="font-mono text-[11px] italic leading-snug text-center self-end w-full"
          style={{
            color: "rgba(255,255,255,0.4)",
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {persona.tagline}
        </p>
      </div>

      {/* Chat zones — absolute overlay above menu bar */}
      <div className="absolute top-0 left-0 right-0 bottom-[48px] flex">
        {/* Continue zone — left 2/3 */}
        <button
          className="flex-[2] flex items-end justify-center pb-2 bg-transparent border-none cursor-pointer"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={() => onContinue(persona.id)}
          onMouseEnter={() => setHoveredZone("continue")}
          onMouseLeave={() => setHoveredZone(null)}
        >
          <span
            className="text-[10px] font-semibold uppercase tracking-[1.5px] transition-all duration-250"
            style={{
              color: hoveredZone === "continue"
                ? chakra.hex + "b3"
                : chakra.hex + "26",
              textShadow: hoveredZone === "continue"
                ? `0 0 12px ${chakra.glow}`
                : "none",
            }}
          >
            Continue
          </span>
        </button>

        {/* Divider line */}
        <div
          className="w-px transition-colors duration-300 self-stretch my-[15%]"
          style={{
            background: isHovered ? chakra.hex + "26" : "transparent",
          }}
        />

        {/* New zone — right 1/3 */}
        <button
          className="flex-[1] flex items-end justify-center pb-2 bg-transparent border-none cursor-pointer"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={() => onNewChat(persona.id)}
          onMouseEnter={() => setHoveredZone("new")}
          onMouseLeave={() => setHoveredZone(null)}
        >
          <span
            className="text-[10px] font-semibold uppercase tracking-[1.5px] transition-all duration-250"
            style={{
              color: hoveredZone === "new"
                ? chakra.hex + "b3"
                : chakra.hex + "26",
              textShadow: hoveredZone === "new"
                ? `0 0 12px ${chakra.glow}`
                : "none",
            }}
          >
            New
          </span>
        </button>
      </div>

      {/* Menu bar — bottom */}
      <div
        className="flex h-12 relative z-[3]"
        style={{ borderTop: `1px solid rgba(255,255,255,0.06)` }}
      >
        {menuButtons.map((btn, i) => (
          <button
            key={btn.tab}
            className="flex-1 flex items-center justify-center text-[10px] font-medium uppercase tracking-[1px] transition-colors duration-200 bg-transparent border-none cursor-pointer"
            style={{
              color: "rgba(255,255,255,0.35)",
              borderRight: i < menuButtons.length - 1
                ? "1px solid rgba(255,255,255,0.04)"
                : "none",
            }}
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
            {btn.label}
          </button>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/components/persona-card/PersonaCard.tsx
git commit -m "Rewrite PersonaCard with new layout, chat zones, and menu bar"
```

---

### Task 3: Update PersonasPage Handlers

**Files:**
- Modify: `frontend/src/app/pages/PersonasPage.tsx`

- [ ] **Step 1: Update handler signatures and fix navigation**

Changes:
1. `handleOpenOverlay` now accepts a `tab` parameter
2. `handleNewChat` appends `?new=1` to the URL
3. Remove the old single-tab `onOpenOverlay` prop — pass the new signature
4. Update `DragOverlay` to pass the updated props

```tsx
import {
  closestCenter,
  DndContext,
  DragOverlay,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core"
import { rectSortingStrategy, SortableContext } from "@dnd-kit/sortable"
import { useState } from "react"
import { useNavigate, useOutletContext } from "react-router-dom"
import PersonaCard from "../components/persona-card/PersonaCard"
import AddPersonaCard from "../components/persona-card/AddPersonaCard"
import { usePersonas } from "../../core/hooks/usePersonas"
import { useSanitisedMode } from "../../core/store/sanitisedModeStore"
import type { PersonaOverlayTab } from "../components/persona-overlay/PersonaOverlay"

export default function PersonasPage() {
  const { personas, reorder } = usePersonas()
  const isSanitised = useSanitisedMode((s) => s.isSanitised)
  const navigate = useNavigate()
  const { openPersonaOverlay } = useOutletContext<{
    openPersonaOverlay: (personaId: string | null, tab?: PersonaOverlayTab) => void
  }>()
  const [activeId, setActiveId] = useState<string | null>(null)

  const filtered = isSanitised ? personas.filter((p) => !p.nsfw) : personas
  const activePersona = filtered.find((p) => p.id === activeId)

  const handleDragStart = (event: DragStartEvent) => {
    setActiveId(event.active.id as string)
  }

  const handleDragEnd = (event: DragEndEvent) => {
    setActiveId(null)
    const { active, over } = event
    if (!over || active.id === over.id) return
    const oldIndex = filtered.findIndex((p) => p.id === active.id)
    const newIndex = filtered.findIndex((p) => p.id === over.id)
    if (oldIndex === -1 || newIndex === -1) return
    const reordered = [...filtered]
    const [moved] = reordered.splice(oldIndex, 1)
    reordered.splice(newIndex, 0, moved)
    reorder(reordered.map((p) => p.id))
  }

  const handleContinue = (personaId: string) => {
    navigate(`/chat/${personaId}`)
  }

  const handleNewChat = (personaId: string) => {
    navigate(`/chat/${personaId}?new=1`)
  }

  const handleOpenOverlay = (personaId: string, tab: PersonaOverlayTab) => {
    openPersonaOverlay(personaId, tab)
  }

  const handleAddPersona = () => {
    openPersonaOverlay(null, "edit")
  }

  return (
    <div className="h-full overflow-y-auto p-10">
      <DndContext
        collisionDetection={closestCenter}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
      >
        <SortableContext items={filtered.map((p) => p.id)} strategy={rectSortingStrategy}>
          <div
            className="flex flex-wrap justify-center gap-6"
            style={{ maxWidth: "1200px", margin: "0 auto" }}
          >
            {filtered.map((persona, index) => (
              <PersonaCard
                key={persona.id}
                persona={persona}
                index={index}
                onContinue={handleContinue}
                onNewChat={handleNewChat}
                onOpenOverlay={handleOpenOverlay}
              />
            ))}
            <AddPersonaCard onClick={handleAddPersona} index={filtered.length} />
          </div>
        </SortableContext>
        <DragOverlay>
          {activePersona ? (
            <div style={{ transform: "scale(1.05)", opacity: 0.9 }}>
              <PersonaCard
                persona={activePersona}
                index={0}
                onContinue={() => {}}
                onNewChat={() => {}}
                onOpenOverlay={() => {}}
              />
            </div>
          ) : null}
        </DragOverlay>
      </DndContext>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/app/pages/PersonasPage.tsx
git commit -m "Update PersonasPage handlers for new card props and fix new-chat navigation"
```

---

### Task 4: Wire Suggested Colour Into PersonaOverlay

**Files:**
- Modify: `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx`

- [ ] **Step 1: Import suggestColour and pass dynamic default colour**

Replace the hardcoded `colour_scheme: 'heart'` in `DEFAULT_PERSONA` with a dynamically computed value. The overlay receives `persona: null` when creating, so we compute the suggestion at render time.

In `PersonaOverlay.tsx`, make these changes:

1. Add a new prop `allPersonas` to receive the full persona list for colour counting
2. Compute `suggestedColour` using `suggestColour` when `isCreating` is true
3. Use it in the resolved persona

```tsx
// Add import at top of file:
import { suggestColour } from '../../../core/utils/suggestColour'

// Add allPersonas to the props interface:
interface PersonaOverlayProps {
  persona: PersonaDto | null
  allPersonas: PersonaDto[]  // <-- add this
  isCreating?: boolean
  activeTab: PersonaOverlayTab
  onClose: () => void
  onTabChange: (tab: PersonaOverlayTab) => void
  onSave: (personaId: string | null, data: Record<string, unknown>) => Promise<void>
}

// Update the component signature:
export function PersonaOverlay({ persona, allPersonas, isCreating, activeTab, onClose, onTabChange, onSave }: PersonaOverlayProps) {
```

Replace the `resolved` line:

```tsx
  // Before:
  const resolved = persona ?? (isCreating ? DEFAULT_PERSONA : null)

  // After:
  const resolved = persona ?? (isCreating
    ? {
        ...DEFAULT_PERSONA,
        colour_scheme: suggestColour(allPersonas.map((p) => p.colour_scheme)),
      }
    : null)
```

- [ ] **Step 2: Pass allPersonas from AppLayout**

In `frontend/src/app/layouts/AppLayout.tsx`, update the `PersonaOverlay` usage (around line 196):

```tsx
  // Before:
  <PersonaOverlay
    persona={overlayPersona}
    isCreating={personaOverlay.personaId === null}
    ...
  />

  // After:
  <PersonaOverlay
    persona={overlayPersona}
    allPersonas={allPersonas}
    isCreating={personaOverlay.personaId === null}
    activeTab={personaOverlay.tab}
    onClose={closePersonaOverlay}
    onTabChange={handlePersonaOverlayTabChange}
    onSave={handlePersonaSave}
  />
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/core/utils/suggestColour.ts \
       frontend/src/app/components/persona-overlay/PersonaOverlay.tsx \
       frontend/src/app/layouts/AppLayout.tsx
git commit -m "Use least-used colour suggestion when creating new persona"
```

---

### Task 5: Visual Verification and Cleanup

**Files:**
- Review: all modified files

- [ ] **Step 1: Run the dev server and verify**

```bash
cd frontend && pnpm dev
```

Verify:
1. Persona cards show new layout: name top, avatar centre, tagline bottom (truncated at 2 lines)
2. Drag handle (6 dots top-left) works for reordering; clicking card body does not drag
3. Hovering over left 2/3 glows "Continue" label, right 1/3 glows "New" label
4. Divider line appears on card hover
5. Continue navigates to `/chat/{id}`, New navigates to `/chat/{id}?new=1`
6. Menu buttons (Overview/Edit/History) open the overlay on the correct tab
7. Creating a new persona suggests a colour different from existing ones
8. NSFW indicator still shows on relevant cards
9. DragOverlay still works during reorder

- [ ] **Step 2: Commit any fixes**

```bash
git add -u
git commit -m "Fix visual issues found during persona card verification"
```

- [ ] **Step 3: Merge to master**

```bash
git checkout master && git merge --no-ff <branch> -m "Merge persona card redesign"
```
