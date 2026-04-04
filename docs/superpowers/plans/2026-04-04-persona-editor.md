# Persona Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Persona Editor — persona cards on a responsive grid page, a 5-tab persona overlay modal, monogram generation, and the Kundalini chakra colour system.

**Architecture:** Backend-first approach. Start with data model changes and the monogram algorithm, then shared DTOs, then frontend types and chakra palette, then build UI components bottom-up (Card → Page → Overlay). The overlay follows the existing Admin/User modal pattern exactly.

**Tech Stack:** Python/FastAPI (backend), Pydantic v2 (DTOs), MongoDB (storage), React 19 + TypeScript + Tailwind CSS v4 (frontend), dnd-kit (drag & drop), Zustand (state), Lora/monospace fonts.

**Spec:** `docs/superpowers/specs/2026-04-04-persona-editor-design.md`

---

## File Map

### Backend — Create
- `backend/modules/persona/_monogram.py` — monogram generation algorithm

### Backend — Modify
- `backend/modules/persona/_models.py` — add `monogram`, `pinned`, `profile_image` fields; change `colour_scheme` to enum
- `backend/modules/persona/_repository.py` — integrate monogram generation on create/update, add `to_dto()` mapping for new fields
- `backend/modules/persona/_handlers.py` — call monogram generation on create/update name changes
- `backend/modules/persona/__init__.py` — no changes needed (public API unchanged)

### Shared — Modify
- `shared/dtos/persona.py` — add new fields, change `colour_scheme` to `Literal` enum type
- `shared/events/persona.py` — no changes needed (events carry full PersonaDto which gets new fields automatically)
- `shared/topics.py` — no changes needed

### Frontend — Create
- `frontend/src/core/types/chakra.ts` — `ChakraColour` type, `CHAKRA_PALETTE` constant with hex/glow/gradient per chakra
- `frontend/src/app/components/persona-card/PersonaCard.tsx` — persona card component
- `frontend/src/app/components/persona-card/AddPersonaCard.tsx` — add-new card placeholder
- `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx` — overlay modal shell with tab navigation
- `frontend/src/app/components/persona-overlay/OverviewTab.tsx` — overview tab content
- `frontend/src/app/components/persona-overlay/EditTab.tsx` — edit form tab
- `frontend/src/app/components/persona-overlay/KnowledgeTab.tsx` — knowledge libraries tab (placeholder)
- `frontend/src/app/components/persona-overlay/MemoriesTab.tsx` — memories tab (placeholder)
- `frontend/src/app/components/persona-overlay/HistoryTab.tsx` — history tab (placeholder)

### Frontend — Modify
- `frontend/src/core/types/persona.ts` — add `monogram`, `pinned`, `profile_image` fields; change `colour_scheme` type
- `frontend/src/core/api/personas.ts` — add `reorder()` API call
- `frontend/src/core/hooks/usePersonas.ts` — add reorder support
- `frontend/src/app/pages/PersonasPage.tsx` — full rewrite: responsive grid, drag & drop, card rendering
- `frontend/src/app/components/sidebar/PersonaItem.tsx` — update to use chakra colours and monogram
- `frontend/src/app/components/sidebar/personaColour.ts` — replace with chakra palette lookup
- `frontend/src/app/components/sidebar/Sidebar.tsx` — update persona section for pinned filtering, sanitised mode
- `frontend/src/app/layouts/AppLayout.tsx` — add persona overlay state, pass to sidebar, sanitised mode for history/projects
- `frontend/src/index.css` — no changes needed (existing theme variables sufficient)

---

## Task 1: Chakra Colour Enum and Backend Model Changes

**Files:**
- Modify: `shared/dtos/persona.py`
- Modify: `backend/modules/persona/_models.py`
- Modify: `backend/modules/persona/_repository.py:76-92` (to_dto method)

- [ ] **Step 1: Update shared DTOs with new fields and chakra enum**

```python
# shared/dtos/persona.py
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ChakraColour = Literal[
    "root", "sacral", "solar", "heart", "throat", "third_eye", "crown"
]


class PersonaDto(BaseModel):
    id: str
    user_id: str
    name: str
    tagline: str
    model_unique_id: str
    system_prompt: str
    temperature: float = Field(ge=0.0, le=2.0)
    reasoning_enabled: bool
    nsfw: bool
    colour_scheme: ChakraColour
    display_order: int
    monogram: str
    pinned: bool
    profile_image: str | None
    created_at: datetime
    updated_at: datetime


class CreatePersonaDto(BaseModel):
    name: str
    tagline: str
    model_unique_id: str
    system_prompt: str
    temperature: float = Field(default=0.8, ge=0.0, le=2.0)
    reasoning_enabled: bool = False
    nsfw: bool = False
    colour_scheme: ChakraColour = "solar"
    display_order: int = 0
    pinned: bool = False
    profile_image: str | None = None


class UpdatePersonaDto(BaseModel):
    name: str | None = None
    tagline: str | None = None
    model_unique_id: str | None = None
    system_prompt: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    reasoning_enabled: bool | None = None
    nsfw: bool | None = None
    colour_scheme: ChakraColour | None = None
    display_order: int | None = None
    pinned: bool | None = None
    profile_image: str | None = None
```

- [ ] **Step 2: Update PersonaDocument model**

```python
# backend/modules/persona/_models.py
from datetime import datetime

from pydantic import BaseModel, Field


class PersonaDocument(BaseModel):
    model_config = {"populate_by_name": True}

    id: str = Field(alias="_id")
    user_id: str
    name: str
    tagline: str
    model_unique_id: str
    system_prompt: str
    temperature: float
    reasoning_enabled: bool
    nsfw: bool
    colour_scheme: str
    display_order: int
    monogram: str
    pinned: bool
    profile_image: str | None
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 3: Update repository to_dto and create methods for new fields**

In `backend/modules/persona/_repository.py`, update the `to_dto()` static method (around line 76) to include new fields:

```python
    @staticmethod
    def to_dto(doc: dict) -> PersonaDto:
        return PersonaDto(
            id=doc["_id"],
            user_id=doc["user_id"],
            name=doc["name"],
            tagline=doc["tagline"],
            model_unique_id=doc["model_unique_id"],
            system_prompt=doc["system_prompt"],
            temperature=doc["temperature"],
            reasoning_enabled=doc["reasoning_enabled"],
            nsfw=doc["nsfw"],
            colour_scheme=doc["colour_scheme"],
            display_order=doc["display_order"],
            monogram=doc.get("monogram", "??"),
            pinned=doc.get("pinned", False),
            profile_image=doc.get("profile_image"),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
        )
```

Update the `create()` method to include new fields in the document dict:

```python
        doc = {
            "_id": str(uuid4()),
            "user_id": user_id,
            "name": dto.name,
            "tagline": dto.tagline,
            "model_unique_id": dto.model_unique_id,
            "system_prompt": dto.system_prompt,
            "temperature": dto.temperature,
            "reasoning_enabled": dto.reasoning_enabled,
            "nsfw": dto.nsfw,
            "colour_scheme": dto.colour_scheme,
            "display_order": dto.display_order,
            "monogram": "",  # placeholder — set by handler after generation
            "pinned": dto.pinned,
            "profile_image": dto.profile_image,
            "created_at": now,
            "updated_at": now,
        }
```

- [ ] **Step 4: Verify backend starts without errors**

Run: `cd /home/chris/workspace/chatsune && uv run python -c "from shared.dtos.persona import PersonaDto, CreatePersonaDto, ChakraColour; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add shared/dtos/persona.py backend/modules/persona/_models.py backend/modules/persona/_repository.py
git commit -m "Add monogram, pinned, profile_image fields and chakra colour enum to persona model"
```

---

## Task 2: Monogram Generation Algorithm

**Files:**
- Create: `backend/modules/persona/_monogram.py`
- Modify: `backend/modules/persona/_handlers.py`
- Modify: `backend/modules/persona/_repository.py` (add method to list existing monograms)

- [ ] **Step 1: Add list_monograms_for_user to repository**

Add this method to `PersonaRepository` in `backend/modules/persona/_repository.py`, after the `delete()` method:

```python
    async def list_monograms_for_user(
        self, user_id: str, exclude_persona_id: str | None = None,
    ) -> set[str]:
        query: dict = {"user_id": user_id, "monogram": {"$exists": True, "$ne": ""}}
        if exclude_persona_id:
            query["_id"] = {"$ne": exclude_persona_id}
        cursor = self._collection.find(query, {"monogram": 1})
        docs = await cursor.to_list(length=500)
        return {doc["monogram"] for doc in docs}
```

- [ ] **Step 2: Create monogram generation module**

```python
# backend/modules/persona/_monogram.py
import re
import string


def generate_monogram(name: str, existing: set[str]) -> str:
    letters = re.sub(r"[^a-zA-Z]", "", name)

    # Strategy 1: multi-part name — first + last initial
    parts = name.split()
    if len(parts) >= 2:
        first_initial = _first_letter(parts[0])
        last_initial = _first_letter(parts[-1])
        if first_initial and last_initial:
            candidate = (first_initial + last_initial).upper()
            if candidate not in existing:
                return candidate

    # Strategy 2: letter combinations from the name
    if letters:
        upper = letters.upper()
        # Try first two distinct letters
        for i in range(len(upper)):
            for j in range(i + 1, len(upper)):
                candidate = upper[i] + upper[j]
                if candidate not in existing:
                    return candidate
        # Try first letter doubled
        candidate = upper[0] + upper[0]
        if candidate not in existing:
            return candidate

    # Strategy 3: no usable letters — iterate AA, AB, AC...
    for first in string.ascii_uppercase:
        for second in string.ascii_uppercase:
            candidate = first + second
            if candidate not in existing:
                return candidate

    # Should never reach here (676 combinations)
    return "??"


def _first_letter(part: str) -> str | None:
    for ch in part:
        if ch.isalpha():
            return ch
    return None
```

- [ ] **Step 3: Integrate monogram generation into handlers**

In `backend/modules/persona/_handlers.py`, add import at the top:

```python
from backend.modules.persona._monogram import generate_monogram
```

In the `create_persona` handler (around line 47), after creating the persona via repository but before publishing the event, generate and set the monogram:

```python
    # After: result = await repo.create(user_id, body)
    existing_monograms = await repo.list_monograms_for_user(user_id)
    monogram = generate_monogram(body.name, existing_monograms)
    await repo.update(result["_id"], user_id, {"monogram": monogram})
    result["monogram"] = monogram
```

In the `patch_persona` handler (around line 131), if name changed, regenerate monogram:

```python
    # After the existing update logic, before publishing event:
    if body.name is not None:
        existing_monograms = await repo.list_monograms_for_user(
            user_id, exclude_persona_id=persona_id,
        )
        monogram = generate_monogram(body.name, existing_monograms)
        await repo.update(persona_id, user_id, {"monogram": monogram})
        updated["monogram"] = monogram
```

Similarly in `replace_persona` (around line 97), regenerate monogram on full replace:

```python
    # After the existing replace logic:
    existing_monograms = await repo.list_monograms_for_user(
        user_id, exclude_persona_id=persona_id,
    )
    monogram = generate_monogram(body.name, existing_monograms)
    await repo.update(persona_id, user_id, {"monogram": monogram})
```

- [ ] **Step 4: Verify monogram generation works**

Run: `cd /home/chris/workspace/chatsune && uv run python -c "
from backend.modules.persona._monogram import generate_monogram
print(generate_monogram('John von Neumann', set()))  # JN
print(generate_monogram('Akira', set()))  # AK
print(generate_monogram('Akira', {'AK'}))  # AI or AR
print(generate_monogram('💫✨🌙', set()))  # AA
"`
Expected: `JN`, `AK`, a two-letter combo not `AK`, `AA`

- [ ] **Step 5: Commit**

```bash
git add backend/modules/persona/_monogram.py backend/modules/persona/_handlers.py backend/modules/persona/_repository.py
git commit -m "Add monogram generation algorithm for personas"
```

---

## Task 3: Frontend Types and Chakra Palette

**Files:**
- Create: `frontend/src/core/types/chakra.ts`
- Modify: `frontend/src/core/types/persona.ts`
- Modify: `frontend/src/app/components/sidebar/personaColour.ts`

- [ ] **Step 1: Create chakra palette type and constants**

```typescript
// frontend/src/core/types/chakra.ts

export type ChakraColour =
  | "root"
  | "sacral"
  | "solar"
  | "heart"
  | "throat"
  | "third_eye"
  | "crown";

export interface ChakraPaletteEntry {
  hex: string;
  glow: string;
  gradient: string;
  sanskrit: string;
  label: string;
}

export const CHAKRA_PALETTE: Record<ChakraColour, ChakraPaletteEntry> = {
  root: {
    hex: "#EB5A5A",
    glow: "rgba(235,90,90,0.3)",
    gradient: "linear-gradient(180deg, rgba(235,90,90,0.08) 0%, transparent 60%)",
    sanskrit: "muladhara",
    label: "Root",
  },
  sacral: {
    hex: "#E67E32",
    glow: "rgba(230,126,50,0.3)",
    gradient: "linear-gradient(180deg, rgba(230,126,50,0.08) 0%, transparent 60%)",
    sanskrit: "svadhisthana",
    label: "Sacral",
  },
  solar: {
    hex: "#C9A84C",
    glow: "rgba(201,168,76,0.3)",
    gradient: "linear-gradient(180deg, rgba(201,168,76,0.08) 0%, transparent 60%)",
    sanskrit: "manipura",
    label: "Solar Plexus",
  },
  heart: {
    hex: "#4CB464",
    glow: "rgba(76,180,100,0.3)",
    gradient: "linear-gradient(180deg, rgba(76,180,100,0.08) 0%, transparent 60%)",
    sanskrit: "anahata",
    label: "Heart",
  },
  throat: {
    hex: "#508CDC",
    glow: "rgba(80,140,220,0.3)",
    gradient: "linear-gradient(180deg, rgba(80,140,220,0.08) 0%, transparent 60%)",
    sanskrit: "vishuddha",
    label: "Throat",
  },
  third_eye: {
    hex: "#8C76D7",
    glow: "rgba(140,118,215,0.3)",
    gradient: "linear-gradient(180deg, rgba(140,118,215,0.08) 0%, transparent 60%)",
    sanskrit: "ajna",
    label: "Third Eye",
  },
  crown: {
    hex: "#A05AC8",
    glow: "rgba(160,90,200,0.3)",
    gradient: "linear-gradient(180deg, rgba(160,90,200,0.08) 0%, transparent 60%)",
    sanskrit: "sahasrara",
    label: "Crown",
  },
};
```

- [ ] **Step 2: Update frontend persona types**

```typescript
// frontend/src/core/types/persona.ts
import type { ChakraColour } from "./chakra";

export interface PersonaDto {
  id: string;
  user_id: string;
  name: string;
  tagline: string;
  model_unique_id: string;
  system_prompt: string;
  temperature: number;
  reasoning_enabled: boolean;
  nsfw: boolean;
  colour_scheme: ChakraColour;
  display_order: number;
  monogram: string;
  pinned: boolean;
  profile_image: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreatePersonaRequest {
  name: string;
  tagline: string;
  model_unique_id: string;
  system_prompt: string;
  temperature?: number;
  reasoning_enabled?: boolean;
  nsfw?: boolean;
  colour_scheme?: ChakraColour;
  display_order?: number;
  pinned?: boolean;
  profile_image?: string | null;
}

export interface UpdatePersonaRequest {
  name?: string;
  tagline?: string;
  model_unique_id?: string;
  system_prompt?: string;
  temperature?: number;
  reasoning_enabled?: boolean;
  nsfw?: boolean;
  colour_scheme?: ChakraColour;
  display_order?: number;
  pinned?: boolean;
  profile_image?: string | null;
}
```

- [ ] **Step 3: Replace personaColour.ts with chakra palette lookup**

```typescript
// frontend/src/app/components/sidebar/personaColour.ts
import { CHAKRA_PALETTE, type ChakraColour } from "../../../core/types/chakra";

export function personaGradient(persona: { colour_scheme: string }): string {
  const entry = CHAKRA_PALETTE[persona.colour_scheme as ChakraColour];
  if (entry) {
    return `linear-gradient(135deg, ${entry.hex}50, ${entry.hex}10)`;
  }
  // Fallback for legacy data
  return `linear-gradient(135deg, #C9A84C50, #C9A84C10)`;
}

export function personaHex(persona: { colour_scheme: string }): string {
  const entry = CHAKRA_PALETTE[persona.colour_scheme as ChakraColour];
  return entry?.hex ?? "#C9A84C";
}

export function personaInitial(persona: { name: string }): string {
  return persona.name.charAt(0).toUpperCase();
}
```

- [ ] **Step 4: Verify frontend compiles**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit 2>&1 | head -20`
Expected: No errors (or only pre-existing unrelated errors)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/core/types/chakra.ts frontend/src/core/types/persona.ts frontend/src/app/components/sidebar/personaColour.ts
git commit -m "Add chakra colour system and update persona types"
```

---

## Task 4: Persona Card Component

**Files:**
- Create: `frontend/src/app/components/persona-card/PersonaCard.tsx`
- Create: `frontend/src/app/components/persona-card/AddPersonaCard.tsx`

- [ ] **Step 1: Create PersonaCard component**

```tsx
// frontend/src/app/components/persona-card/PersonaCard.tsx
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { CHAKRA_PALETTE, type ChakraColour } from "../../../core/types/chakra";
import type { PersonaDto } from "../../../core/types/persona";

interface PersonaCardProps {
  persona: PersonaDto;
  onContinue: (personaId: string) => void;
  onNewChat: (personaId: string) => void;
  onOpenOverlay: (personaId: string) => void;
}

export default function PersonaCard({
  persona,
  onContinue,
  onNewChat,
  onOpenOverlay,
}: PersonaCardProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: persona.id });

  const chakra = CHAKRA_PALETTE[persona.colour_scheme as ChakraColour] ??
    CHAKRA_PALETTE.solar;
  const hex = chakra.hex;

  const style = {
    transform: CSS.Transform.toString(transform),
    transition: transition ?? "transform 250ms ease",
    opacity: isDragging ? 0.15 : 1,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      className="group relative flex flex-col items-center rounded-3xl border cursor-grab active:cursor-grabbing"
      style={{
        ...style,
        width: "clamp(160px, 42vw, 210px)",
        height: "clamp(240px, 63vw, 320px)",
        background: `linear-gradient(180deg, ${hex}0A 0%, #0a0810 60%)`,
        borderColor: `${hex}33`,
      }}
    >
      {/* NSFW indicator */}
      {persona.nsfw && (
        <span
          className="absolute top-3 left-3.5 text-sm"
          style={{ opacity: 0.4 }}
          title="NSFW"
        >
          💋
        </span>
      )}

      {/* Monogram badge */}
      <div
        className="absolute top-3 right-3.5 font-mono text-[10px] tracking-widest rounded-md px-1.5 py-0.5 border"
        style={{ color: `${hex}99`, borderColor: `${hex}33` }}
      >
        {persona.monogram}
      </div>

      {/* Avatar */}
      <div className="flex-1 flex flex-col items-center justify-center">
        <div
          className="w-[100px] h-[100px] rounded-full flex items-center justify-center"
          style={{
            background: `radial-gradient(circle, ${hex}40 0%, ${hex}08 80%)`,
            boxShadow: `0 0 40px ${hex}1A`,
          }}
        >
          {persona.profile_image ? (
            <img
              src={persona.profile_image}
              alt={persona.name}
              className="w-full h-full rounded-full object-cover"
            />
          ) : (
            <span
              className="text-3xl font-serif"
              style={{ color: `${hex}DD` }}
            >
              {persona.monogram}
            </span>
          )}
        </div>

        {/* Name & Tagline */}
        <div className="mt-5 text-center px-4">
          <div
            className="font-serif text-xl tracking-wide"
            style={{ color: "#e8e0d4" }}
          >
            {persona.name}
          </div>
          <div
            className="font-mono text-[10px] uppercase tracking-[2px] mt-1.5"
            style={{ color: "rgba(232,224,212,0.35)" }}
          >
            {persona.tagline}
          </div>
        </div>
      </div>

      {/* Overlay trigger */}
      <button
        onClick={(e) => {
          e.stopPropagation();
          onOpenOverlay(persona.id);
        }}
        onPointerDown={(e) => e.stopPropagation()}
        className="mb-2 w-7 h-7 rounded-full border flex items-center justify-center transition-colors hover:bg-white/5"
        style={{ borderColor: `${hex}26`, color: `${hex}66` }}
        title="Persona details"
      >
        <span className="text-xs">⟡</span>
      </button>

      {/* Action zones */}
      <div
        className="w-full flex"
        style={{ borderTop: `1px solid ${hex}15` }}
      >
        <button
          onClick={(e) => {
            e.stopPropagation();
            onContinue(persona.id);
          }}
          onPointerDown={(e) => e.stopPropagation()}
          className="flex-[2] flex items-center justify-center gap-2 py-4 transition-colors hover:bg-white/5"
          style={{ borderRight: `1px solid ${hex}15` }}
        >
          <span className="text-sm" style={{ opacity: 0.4 }}>
            →
          </span>
          <span
            className="font-mono text-[10px] uppercase tracking-wider"
            style={{ color: "rgba(232,224,212,0.35)" }}
          >
            continue
          </span>
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onNewChat(persona.id);
          }}
          onPointerDown={(e) => e.stopPropagation()}
          className="flex-1 flex items-center justify-center gap-1.5 py-4 transition-colors hover:bg-white/5"
        >
          <span className="text-xs" style={{ opacity: 0.4 }}>
            +
          </span>
          <span
            className="font-mono text-[9px] uppercase tracking-wider"
            style={{ color: "rgba(232,224,212,0.3)" }}
          >
            new
          </span>
        </button>
      </div>
    </div>
  );
}
```

Note: The component has a duplicate `style` prop issue — the agentic worker should merge the inline styles with the transform/transition/opacity into a single `style` object and keep `className` for Tailwind classes only.

- [ ] **Step 2: Create AddPersonaCard component**

```tsx
// frontend/src/app/components/persona-card/AddPersonaCard.tsx

interface AddPersonaCardProps {
  onClick: () => void;
}

export default function AddPersonaCard({ onClick }: AddPersonaCardProps) {
  return (
    <button
      onClick={onClick}
      className="flex flex-col items-center justify-center rounded-3xl border-2 border-dashed transition-all duration-300 hover:-translate-y-1 hover:border-opacity-50 cursor-pointer"
      style={{
        width: "clamp(160px, 42vw, 210px)",
        height: "clamp(240px, 63vw, 320px)",
        borderColor: "rgba(201,168,76,0.15)",
      }}
    >
      <span
        className="text-3xl mb-2"
        style={{ color: "rgba(201,168,76,0.3)" }}
      >
        +
      </span>
      <span
        className="font-mono text-[10px] uppercase tracking-[2px]"
        style={{ color: "rgba(201,168,76,0.3)" }}
      >
        add persona
      </span>
    </button>
  );
}
```

- [ ] **Step 3: Verify frontend compiles**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit 2>&1 | head -20`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/persona-card/
git commit -m "Add PersonaCard and AddPersonaCard components"
```

---

## Task 5: Personas Page with Responsive Grid and Drag & Drop

**Files:**
- Modify: `frontend/src/app/pages/PersonasPage.tsx` (full rewrite)
- Modify: `frontend/src/core/api/personas.ts` (add reorder endpoint)
- Modify: `frontend/src/core/hooks/usePersonas.ts` (add reorder support)

- [ ] **Step 1: Add reorder API call**

Add to `frontend/src/core/api/personas.ts`, inside the `personasApi` object:

```typescript
  reorder: async (orderedIds: string[]): Promise<void> => {
    await client.patch("/api/personas/reorder", { ordered_ids: orderedIds });
  },
```

- [ ] **Step 2: Add reorder to usePersonas hook**

Add to `frontend/src/core/hooks/usePersonas.ts`, inside the hook, after the `remove` function:

```typescript
  const reorder = async (orderedIds: string[]) => {
    // Optimistic: reorder local state immediately
    setPersonas((prev) => {
      const map = new Map(prev.map((p) => [p.id, p]));
      return orderedIds.map((id) => map.get(id)!).filter(Boolean);
    });
    try {
      await personasApi.reorder(orderedIds);
    } catch {
      await fetch(); // rollback on failure
    }
  };
```

Update the return statement to include `reorder`.

- [ ] **Step 3: Add reorder endpoint to backend**

Add to `backend/modules/persona/_handlers.py`:

```python
@router.patch("/reorder")
async def reorder_personas(
    body: dict,
    session: dict = Depends(require_active_session),
):
    user_id = session["user_id"]
    ordered_ids: list[str] = body.get("ordered_ids", [])
    for index, persona_id in enumerate(ordered_ids):
        await repo.update(persona_id, user_id, {"display_order": index})
    return {"status": "ok"}
```

Important: This route must be defined **before** the `/{persona_id}` routes in the file, otherwise FastAPI will try to match "reorder" as a persona_id.

- [ ] **Step 4: Rewrite PersonasPage with grid and drag & drop**

```tsx
// frontend/src/app/pages/PersonasPage.tsx
import {
  closestCenter,
  DndContext,
  DragOverlay,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import {
  rectSortingStrategy,
  SortableContext,
} from "@dnd-kit/sortable";
import { useState } from "react";
import { useNavigate } from "react-router";

import PersonaCard from "../components/persona-card/PersonaCard";
import AddPersonaCard from "../components/persona-card/AddPersonaCard";
import { usePersonas } from "../../core/hooks/usePersonas";
import { useSanitisedModeStore } from "../../core/store/sanitisedModeStore";
import type { PersonaDto } from "../../core/types/persona";

export default function PersonasPage() {
  const { personas, reorder } = usePersonas();
  const isSanitised = useSanitisedModeStore((s) => s.isSanitised);
  const navigate = useNavigate();
  const [activeId, setActiveId] = useState<string | null>(null);

  const filtered = isSanitised
    ? personas.filter((p) => !p.nsfw)
    : personas;

  const activePersona = filtered.find((p) => p.id === activeId);

  const handleDragStart = (event: DragStartEvent) => {
    setActiveId(event.active.id as string);
  };

  const handleDragEnd = (event: DragEndEvent) => {
    setActiveId(null);
    const { active, over } = event;
    if (!over || active.id === over.id) return;

    const oldIndex = filtered.findIndex((p) => p.id === active.id);
    const newIndex = filtered.findIndex((p) => p.id === over.id);
    if (oldIndex === -1 || newIndex === -1) return;

    const reordered = [...filtered];
    const [moved] = reordered.splice(oldIndex, 1);
    reordered.splice(newIndex, 0, moved);
    reorder(reordered.map((p) => p.id));
  };

  const handleContinue = (personaId: string) => {
    // TODO: resolve last session ID from chat module — for now, starts new chat
    navigate(`/chat/${personaId}`);
  };

  const handleNewChat = (personaId: string) => {
    navigate(`/chat/${personaId}`);
  };

  const handleOpenOverlay = (personaId: string) => {
    // TODO: wire to persona overlay in Task 7
  };

  const handleAddPersona = () => {
    // TODO: wire to persona overlay in Task 7 (Edit tab, new persona)
  };

  return (
    <div className="h-full overflow-y-auto p-10">
      <DndContext
        collisionDetection={closestCenter}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
      >
        <SortableContext
          items={filtered.map((p) => p.id)}
          strategy={rectSortingStrategy}
        >
          <div
            className="flex flex-wrap justify-center gap-6"
            style={{
              maxWidth: "1200px",
              margin: "0 auto",
            }}
          >
            {filtered.map((persona) => (
              <PersonaCard
                key={persona.id}
                persona={persona}
                onContinue={handleContinue}
                onNewChat={handleNewChat}
                onOpenOverlay={handleOpenOverlay}
              />
            ))}
            <AddPersonaCard onClick={handleAddPersona} />
          </div>
        </SortableContext>

        <DragOverlay>
          {activePersona ? (
            <div style={{ transform: "scale(1.05)", opacity: 0.9 }}>
              <PersonaCard
                persona={activePersona}
                onContinue={() => {}}
                onNewChat={() => {}}
                onOpenOverlay={() => {}}
              />
            </div>
          ) : null}
        </DragOverlay>
      </DndContext>
    </div>
  );
}
```

- [ ] **Step 5: Install dnd-kit if not already present**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm list @dnd-kit/core 2>/dev/null || pnpm add @dnd-kit/core @dnd-kit/sortable @dnd-kit/utilities`

- [ ] **Step 6: Verify frontend compiles and renders**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit 2>&1 | head -20`
Expected: No errors

- [ ] **Step 7: Commit**

```bash
git add frontend/src/app/pages/PersonasPage.tsx frontend/src/core/api/personas.ts frontend/src/core/hooks/usePersonas.ts backend/modules/persona/_handlers.py
git commit -m "Add Personas Page with responsive grid and drag-and-drop reordering"
```

---

## Task 6: Persona Overlay Shell and Tab Navigation

**Files:**
- Create: `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx`

- [ ] **Step 1: Create the overlay modal shell**

This follows the exact same pattern as `AdminModal.tsx` and `UserModal.tsx` — `absolute inset-4`, focus trap, Escape handling, tab bar.

```tsx
// frontend/src/app/components/persona-overlay/PersonaOverlay.tsx
import { useCallback, useEffect, useRef, useState } from "react";
import { CHAKRA_PALETTE, type ChakraColour } from "../../../core/types/chakra";
import type { PersonaDto } from "../../../core/types/persona";
import OverviewTab from "./OverviewTab";
import EditTab from "./EditTab";
import KnowledgeTab from "./KnowledgeTab";
import MemoriesTab from "./MemoriesTab";
import HistoryTab from "./HistoryTab";

export type PersonaOverlayTab =
  | "overview"
  | "edit"
  | "knowledge"
  | "memories"
  | "history";

interface PersonaOverlayProps {
  persona: PersonaDto | null;
  activeTab: PersonaOverlayTab;
  onClose: () => void;
  onTabChange: (tab: PersonaOverlayTab) => void;
  onSave: (personaId: string, data: Record<string, unknown>) => Promise<void>;
}

const TABS: { id: PersonaOverlayTab; label: string; subtitle?: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "edit", label: "Edit" },
  { id: "knowledge", label: "Knowledge", subtitle: "muladhara" },
  { id: "memories", label: "Memories", subtitle: "anahata" },
  { id: "history", label: "History", subtitle: "vishuddha" },
];

export default function PersonaOverlay({
  persona,
  activeTab,
  onClose,
  onTabChange,
  onSave,
}: PersonaOverlayProps) {
  const modalRef = useRef<HTMLDivElement>(null);

  // Focus trap
  useEffect(() => {
    const modal = modalRef.current;
    if (!modal) return;

    const focusable = modal.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    );
    if (focusable.length > 0) focusable[0].focus();

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key !== "Tab" || focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose, activeTab]);

  if (!persona) return null;

  const chakra = CHAKRA_PALETTE[persona.colour_scheme as ChakraColour] ??
    CHAKRA_PALETTE.solar;

  return (
    <>
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 z-10"
        onClick={onClose}
      />

      {/* Modal */}
      <div
        ref={modalRef}
        className="absolute inset-4 z-20 flex flex-col rounded-xl overflow-hidden"
        style={{
          background: "linear-gradient(180deg, #120f18 0%, #0a0810 100%)",
          border: `1px solid ${chakra.hex}26`,
        }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-6 py-4"
          style={{ borderBottom: `1px solid ${chakra.hex}15` }}
        >
          <div className="flex items-center gap-3">
            <span
              className="font-mono text-xs tracking-widest"
              style={{ color: `${chakra.hex}88` }}
            >
              {persona.monogram}
            </span>
            <span className="font-serif text-lg" style={{ color: "#e8e0d4" }}>
              {persona.name}
            </span>
          </div>
          <button
            onClick={onClose}
            className="text-white/30 hover:text-white/60 transition-colors text-xl leading-none"
          >
            &times;
          </button>
        </div>

        {/* Tab bar */}
        <div
          className="flex gap-1 px-6"
          style={{ borderBottom: `1px solid rgba(255,255,255,0.06)` }}
        >
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => onTabChange(tab.id)}
              className="relative px-4 py-3 text-sm transition-colors"
              style={{
                color:
                  activeTab === tab.id
                    ? chakra.hex
                    : "rgba(255,255,255,0.4)",
              }}
            >
              <span>{tab.label}</span>
              {tab.subtitle && (
                <span
                  className="ml-1.5 font-mono text-[8px] tracking-wider"
                  style={{
                    color:
                      activeTab === tab.id
                        ? `${chakra.hex}66`
                        : "rgba(255,255,255,0.15)",
                  }}
                >
                  {tab.subtitle}
                </span>
              )}
              {activeTab === tab.id && (
                <div
                  className="absolute bottom-0 left-4 right-4 h-0.5 rounded-full"
                  style={{ background: chakra.hex }}
                />
              )}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {activeTab === "overview" && <OverviewTab persona={persona} chakra={chakra} />}
          {activeTab === "edit" && (
            <EditTab persona={persona} chakra={chakra} onSave={onSave} />
          )}
          {activeTab === "knowledge" && <KnowledgeTab persona={persona} chakra={chakra} />}
          {activeTab === "memories" && <MemoriesTab persona={persona} chakra={chakra} />}
          {activeTab === "history" && <HistoryTab persona={persona} chakra={chakra} />}
        </div>
      </div>
    </>
  );
}
```

- [ ] **Step 2: Verify the file was created correctly**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit 2>&1 | head -30`
Expected: Errors only about missing tab components (OverviewTab, EditTab, etc.) — those are created in the next tasks.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/components/persona-overlay/PersonaOverlay.tsx
git commit -m "Add PersonaOverlay modal shell with tab navigation and chakra theming"
```

---

## Task 7: Overlay Tab Components

**Files:**
- Create: `frontend/src/app/components/persona-overlay/OverviewTab.tsx`
- Create: `frontend/src/app/components/persona-overlay/EditTab.tsx`
- Create: `frontend/src/app/components/persona-overlay/KnowledgeTab.tsx`
- Create: `frontend/src/app/components/persona-overlay/MemoriesTab.tsx`
- Create: `frontend/src/app/components/persona-overlay/HistoryTab.tsx`

- [ ] **Step 1: Create OverviewTab**

```tsx
// frontend/src/app/components/persona-overlay/OverviewTab.tsx
import type { ChakraPaletteEntry } from "../../../core/types/chakra";
import type { PersonaDto } from "../../../core/types/persona";

interface OverviewTabProps {
  persona: PersonaDto;
  chakra: ChakraPaletteEntry;
}

export default function OverviewTab({ persona, chakra }: OverviewTabProps) {
  const created = new Date(persona.created_at).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });

  return (
    <div className="flex flex-col items-center pt-4">
      {/* Avatar */}
      <div
        className="w-[120px] h-[120px] rounded-full flex items-center justify-center"
        style={{
          background: `radial-gradient(circle, ${chakra.hex}40 0%, ${chakra.hex}08 80%)`,
          boxShadow: `0 0 60px ${chakra.hex}1A`,
        }}
      >
        {persona.profile_image ? (
          <img
            src={persona.profile_image}
            alt={persona.name}
            className="w-full h-full rounded-full object-cover"
          />
        ) : (
          <span className="text-4xl font-serif" style={{ color: `${chakra.hex}DD` }}>
            {persona.monogram}
          </span>
        )}
      </div>

      {/* Name & Tagline */}
      <h2 className="font-serif text-2xl mt-5" style={{ color: "#e8e0d4" }}>
        {persona.name}
      </h2>
      <p
        className="font-mono text-[10px] uppercase tracking-[2px] mt-1.5"
        style={{ color: "rgba(232,224,212,0.4)" }}
      >
        {persona.tagline}
      </p>

      {/* Stats */}
      <div
        className="grid grid-cols-3 gap-6 mt-8 w-full max-w-md text-center"
      >
        <div>
          <div className="font-serif text-2xl" style={{ color: chakra.hex }}>
            —
          </div>
          <div
            className="font-mono text-[9px] uppercase tracking-wider mt-1"
            style={{ color: "rgba(255,255,255,0.3)" }}
          >
            chats
          </div>
        </div>
        <div>
          <div className="font-serif text-2xl" style={{ color: chakra.hex }}>
            —
          </div>
          <div
            className="font-mono text-[9px] uppercase tracking-wider mt-1"
            style={{ color: "rgba(255,255,255,0.3)" }}
          >
            memory tokens
          </div>
        </div>
        <div>
          <div className="font-serif text-2xl" style={{ color: chakra.hex }}>
            —
          </div>
          <div
            className="font-mono text-[9px] uppercase tracking-wider mt-1"
            style={{ color: "rgba(255,255,255,0.3)" }}
          >
            pending journal
          </div>
        </div>
      </div>

      {/* Meta */}
      <div
        className="mt-8 font-mono text-[10px]"
        style={{ color: "rgba(255,255,255,0.2)" }}
      >
        created {created}
      </div>
    </div>
  );
}
```

Note: Stats show "—" as placeholder. The chat/memory modules don't exist yet. When they're built, these will be replaced with real counts. The structure is ready.

- [ ] **Step 2: Create EditTab**

```tsx
// frontend/src/app/components/persona-overlay/EditTab.tsx
import { useState } from "react";
import {
  CHAKRA_PALETTE,
  type ChakraColour,
  type ChakraPaletteEntry,
} from "../../../core/types/chakra";
import type { PersonaDto } from "../../../core/types/persona";

interface EditTabProps {
  persona: PersonaDto;
  chakra: ChakraPaletteEntry;
  onSave: (personaId: string, data: Record<string, unknown>) => Promise<void>;
}

const CHAKRA_OPTIONS = Object.entries(CHAKRA_PALETTE) as [
  ChakraColour,
  ChakraPaletteEntry,
][];

export default function EditTab({ persona, chakra, onSave }: EditTabProps) {
  const [name, setName] = useState(persona.name);
  const [tagline, setTagline] = useState(persona.tagline);
  const [colourScheme, setColourScheme] = useState<ChakraColour>(
    persona.colour_scheme as ChakraColour,
  );
  const [systemPrompt, setSystemPrompt] = useState(persona.system_prompt);
  const [temperature, setTemperature] = useState(persona.temperature);
  const [reasoningEnabled, setReasoningEnabled] = useState(
    persona.reasoning_enabled,
  );
  const [nsfw, setNsfw] = useState(persona.nsfw);
  const [saving, setSaving] = useState(false);

  const isDirty =
    name !== persona.name ||
    tagline !== persona.tagline ||
    colourScheme !== persona.colour_scheme ||
    systemPrompt !== persona.system_prompt ||
    temperature !== persona.temperature ||
    reasoningEnabled !== persona.reasoning_enabled ||
    nsfw !== persona.nsfw;

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave(persona.id, {
        name,
        tagline,
        colour_scheme: colourScheme,
        system_prompt: systemPrompt,
        temperature,
        reasoning_enabled: reasoningEnabled,
        nsfw,
      });
    } finally {
      setSaving(false);
    }
  };

  const inputStyle = {
    background: "rgba(255,255,255,0.03)",
    border: `1px solid ${chakra.hex}26`,
    borderRadius: "8px",
    padding: "10px 14px",
    color: "#e8e0d4",
  };

  return (
    <div className="max-w-lg mx-auto space-y-5">
      {/* Name */}
      <div>
        <label
          className="font-mono text-[9px] uppercase tracking-wider block mb-1.5"
          style={{ color: "rgba(255,255,255,0.3)" }}
        >
          Name
        </label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-full font-serif text-base outline-none focus:border-white/20 transition-colors"
          style={inputStyle}
        />
      </div>

      {/* Tagline */}
      <div>
        <label
          className="font-mono text-[9px] uppercase tracking-wider block mb-1.5"
          style={{ color: "rgba(255,255,255,0.3)" }}
        >
          Tagline
        </label>
        <input
          type="text"
          value={tagline}
          onChange={(e) => setTagline(e.target.value)}
          className="w-full font-mono text-xs outline-none focus:border-white/20 transition-colors"
          style={inputStyle}
        />
      </div>

      {/* Chakra Colour */}
      <div>
        <label
          className="font-mono text-[9px] uppercase tracking-wider block mb-2"
          style={{ color: "rgba(255,255,255,0.3)" }}
        >
          Colour
        </label>
        <div className="flex gap-3">
          {CHAKRA_OPTIONS.map(([key, entry]) => (
            <button
              key={key}
              onClick={() => setColourScheme(key)}
              className="w-9 h-9 rounded-full transition-all"
              style={{
                background: entry.hex,
                boxShadow:
                  colourScheme === key
                    ? `0 0 16px ${entry.glow}, 0 0 0 2px ${entry.hex}`
                    : "none",
                opacity: colourScheme === key ? 1 : 0.5,
              }}
              title={entry.label}
            />
          ))}
        </div>
      </div>

      {/* System Prompt */}
      <div>
        <label
          className="font-mono text-[9px] uppercase tracking-wider block mb-1.5"
          style={{ color: "rgba(255,255,255,0.3)" }}
        >
          System Prompt
        </label>
        <textarea
          value={systemPrompt}
          onChange={(e) => setSystemPrompt(e.target.value)}
          rows={8}
          className="w-full font-mono text-xs outline-none focus:border-white/20 transition-colors resize-y"
          style={{ ...inputStyle, minHeight: "150px" }}
        />
      </div>

      {/* Temperature */}
      <div>
        <label
          className="font-mono text-[9px] uppercase tracking-wider block mb-1.5"
          style={{ color: "rgba(255,255,255,0.3)" }}
        >
          Temperature:{" "}
          <span style={{ color: chakra.hex }}>{temperature.toFixed(2)}</span>
        </label>
        <input
          type="range"
          min="0"
          max="2"
          step="0.05"
          value={temperature}
          onChange={(e) => setTemperature(parseFloat(e.target.value))}
          className="w-full"
        />
      </div>

      {/* Toggles row */}
      <div className="flex gap-6">
        {/* Reasoning */}
        <label className="flex items-center gap-2 cursor-pointer">
          <div
            className="w-10 h-5 rounded-full relative transition-colors"
            style={{
              background: reasoningEnabled
                ? `${chakra.hex}88`
                : "rgba(255,255,255,0.1)",
            }}
            onClick={() => setReasoningEnabled(!reasoningEnabled)}
          >
            <div
              className="absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform"
              style={{
                transform: reasoningEnabled
                  ? "translateX(22px)"
                  : "translateX(2px)",
              }}
            />
          </div>
          <span
            className="font-mono text-[9px] uppercase tracking-wider"
            style={{ color: "rgba(255,255,255,0.3)" }}
          >
            Reasoning
          </span>
        </label>

        {/* NSFW */}
        <label className="flex items-center gap-2 cursor-pointer">
          <div
            className="w-10 h-5 rounded-full relative transition-colors"
            style={{
              background: nsfw
                ? `${chakra.hex}88`
                : "rgba(255,255,255,0.1)",
            }}
            onClick={() => setNsfw(!nsfw)}
          >
            <div
              className="absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform"
              style={{
                transform: nsfw
                  ? "translateX(22px)"
                  : "translateX(2px)",
              }}
            />
          </div>
          <span
            className="font-mono text-[9px] uppercase tracking-wider"
            style={{ color: "rgba(255,255,255,0.3)" }}
          >
            NSFW
          </span>
        </label>
      </div>

      {/* Save button */}
      <div className="pt-4 flex justify-end">
        <button
          onClick={handleSave}
          disabled={!isDirty || saving || !name.trim()}
          className="font-mono text-xs uppercase tracking-wider px-6 py-2.5 rounded-lg transition-all disabled:opacity-30"
          style={{
            background: isDirty ? chakra.hex : "rgba(255,255,255,0.05)",
            color: isDirty ? "#0a0810" : "rgba(255,255,255,0.3)",
          }}
        >
          {saving ? "Saving..." : "Save"}
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Create KnowledgeTab placeholder**

```tsx
// frontend/src/app/components/persona-overlay/KnowledgeTab.tsx
import type { ChakraPaletteEntry } from "../../../core/types/chakra";
import type { PersonaDto } from "../../../core/types/persona";

interface KnowledgeTabProps {
  persona: PersonaDto;
  chakra: ChakraPaletteEntry;
}

export default function KnowledgeTab({ persona, chakra }: KnowledgeTabProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16">
      <div
        className="font-mono text-[10px] uppercase tracking-[3px]"
        style={{ color: "rgba(255,255,255,0.2)" }}
      >
        knowledge libraries
      </div>
      <div
        className="font-mono text-[8px] mt-1"
        style={{ color: "rgba(255,255,255,0.1)" }}
      >
        coming with the knowledge module
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Create MemoriesTab placeholder**

```tsx
// frontend/src/app/components/persona-overlay/MemoriesTab.tsx
import type { ChakraPaletteEntry } from "../../../core/types/chakra";
import type { PersonaDto } from "../../../core/types/persona";

interface MemoriesTabProps {
  persona: PersonaDto;
  chakra: ChakraPaletteEntry;
}

export default function MemoriesTab({ persona, chakra }: MemoriesTabProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16">
      <div
        className="font-mono text-[10px] uppercase tracking-[3px]"
        style={{ color: "rgba(255,255,255,0.2)" }}
      >
        memories &amp; journal
      </div>
      <div
        className="font-mono text-[8px] mt-1"
        style={{ color: "rgba(255,255,255,0.1)" }}
      >
        coming with the memory module
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Create HistoryTab placeholder**

```tsx
// frontend/src/app/components/persona-overlay/HistoryTab.tsx
import type { ChakraPaletteEntry } from "../../../core/types/chakra";
import type { PersonaDto } from "../../../core/types/persona";

interface HistoryTabProps {
  persona: PersonaDto;
  chakra: ChakraPaletteEntry;
}

export default function HistoryTab({ persona, chakra }: HistoryTabProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16">
      <div
        className="font-mono text-[10px] uppercase tracking-[3px]"
        style={{ color: "rgba(255,255,255,0.2)" }}
      >
        conversation history
      </div>
      <div
        className="font-mono text-[8px] mt-1"
        style={{ color: "rgba(255,255,255,0.1)" }}
      >
        coming with the chat module
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Verify frontend compiles**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit 2>&1 | head -20`
Expected: No errors

- [ ] **Step 7: Commit**

```bash
git add frontend/src/app/components/persona-overlay/
git commit -m "Add persona overlay tab components (Overview, Edit, Knowledge, Memories, History)"
```

---

## Task 8: Wire Overlay into AppLayout and PersonasPage

**Files:**
- Modify: `frontend/src/app/layouts/AppLayout.tsx`
- Modify: `frontend/src/app/pages/PersonasPage.tsx`

- [ ] **Step 1: Add persona overlay state to AppLayout**

In `frontend/src/app/layouts/AppLayout.tsx`, add imports and state for the persona overlay. Add after the existing admin modal state (around line 48):

```tsx
import PersonaOverlay, {
  type PersonaOverlayTab,
} from "../components/persona-overlay/PersonaOverlay";

// Inside the AppLayout component, after adminTab state:
const [personaOverlay, setPersonaOverlay] = useState<{
  personaId: string;
  tab: PersonaOverlayTab;
} | null>(null);

const openPersonaOverlay = useCallback(
  (personaId: string, tab: PersonaOverlayTab = "overview") => {
    setPersonaOverlay({ personaId, tab });
  },
  [],
);

const closePersonaOverlay = useCallback(() => {
  setPersonaOverlay(null);
}, []);

const handlePersonaOverlayTabChange = useCallback(
  (tab: PersonaOverlayTab) => {
    setPersonaOverlay((prev) => (prev ? { ...prev, tab } : null));
  },
  [],
);

const handlePersonaSave = useCallback(
  async (personaId: string, data: Record<string, unknown>) => {
    await personasApi.update(personaId, data);
  },
  [],
);

const overlayPersona = personaOverlay
  ? personas.find((p) => p.id === personaOverlay.personaId) ?? null
  : null;
```

Import `personasApi` at the top:

```tsx
import { personasApi } from "../../core/api/personas";
```

Add the overlay to the JSX, after the existing modals (UserModal, AdminModal):

```tsx
{personaOverlay && (
  <PersonaOverlay
    persona={overlayPersona}
    activeTab={personaOverlay.tab}
    onClose={closePersonaOverlay}
    onTabChange={handlePersonaOverlayTabChange}
    onSave={handlePersonaSave}
  />
)}
```

Pass `openPersonaOverlay` down via the Outlet context or a dedicated prop mechanism. The simplest approach: pass it via React Router's Outlet context.

Replace the `<Outlet />` with:

```tsx
<Outlet context={{ openPersonaOverlay }} />
```

- [ ] **Step 2: Consume overlay context in PersonasPage**

In `frontend/src/app/pages/PersonasPage.tsx`, import and use the context:

```tsx
import { useOutletContext } from "react-router";
import type { PersonaOverlayTab } from "../components/persona-overlay/PersonaOverlay";

// Inside PersonasPage component:
const { openPersonaOverlay } = useOutletContext<{
  openPersonaOverlay: (personaId: string, tab?: PersonaOverlayTab) => void;
}>();

// Replace the handleOpenOverlay function:
const handleOpenOverlay = (personaId: string) => {
  openPersonaOverlay(personaId, "overview");
};

// Replace the handleAddPersona function:
const handleAddPersona = () => {
  // For new personas: create first, then open edit tab
  // For now, open overlay on a temp persona — or create inline
  // Simplest: navigate to create flow
  // TODO: create-and-open flow when persona creation modal is needed
};
```

- [ ] **Step 3: Verify everything compiles and the overlay renders**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit 2>&1 | head -20`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/layouts/AppLayout.tsx frontend/src/app/pages/PersonasPage.tsx
git commit -m "Wire persona overlay into AppLayout and PersonasPage"
```

---

## Task 9: Update Sidebar for Chakra Colours and Pinned Filtering

**Files:**
- Modify: `frontend/src/app/components/sidebar/PersonaItem.tsx`
- Modify: `frontend/src/app/components/sidebar/Sidebar.tsx`

- [ ] **Step 1: Update PersonaItem to use chakra colours and monogram**

In `frontend/src/app/components/sidebar/PersonaItem.tsx`, replace the gradient usage with chakra palette lookup. Update the avatar section to use monogram and chakra hex:

```tsx
import { CHAKRA_PALETTE, type ChakraColour } from "../../../core/types/chakra";

// Inside the component, at the top:
const chakra = CHAKRA_PALETTE[persona.colour_scheme as ChakraColour] ?? CHAKRA_PALETTE.solar;
```

Replace the gradient avatar (around line 55-60) with:

```tsx
<div
  className="w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 text-[9px] font-serif"
  style={{
    background: `radial-gradient(circle, ${chakra.hex}40 0%, ${chakra.hex}10 80%)`,
    color: `${chakra.hex}CC`,
  }}
>
  {persona.monogram || persona.name.charAt(0).toUpperCase()}
</div>
```

Add "Persona" to the menu items array (around line 38-43) to open the overlay:

```tsx
{ label: "Persona", icon: "⟡", action: onOpenOverlay },
```

Update `PersonaItemProps` to include `onOpenOverlay`:

```tsx
onOpenOverlay?: () => void;
```

- [ ] **Step 2: Update Sidebar persona section for pinned filtering and sanitised mode**

In `frontend/src/app/components/sidebar/Sidebar.tsx`, update the personas section (around line 295-327). The personas passed to Sidebar are already filtered for NSFW in AppLayout. Add pinned filtering:

```tsx
// In the expanded personas section, filter for pinned only:
const pinnedPersonas = personas.filter((p) => p.pinned);
```

Use `pinnedPersonas` instead of `personas` when mapping PersonaItem components. This ensures only pinned personas show in the sidebar.

Pass `onOpenOverlay` callback to each PersonaItem:

```tsx
<PersonaItem
  key={p.id}
  persona={p}
  isActive={activePersonaId === p.id}
  onSelect={() => onPersonaSelect(p.id)}
  onNewChat={() => onNewChat(p.id)}
  onNewIncognitoChat={() => onNewIncognitoChat(p.id)}
  onEdit={() => onEdit(p.id)}
  onOpenOverlay={() => onOpenOverlay?.(p.id)}
  onUnpin={() => onUnpin?.(p.id)}
/>
```

Update `SidebarProps` to include `onOpenOverlay`:

```tsx
onOpenOverlay?: (personaId: string) => void;
```

- [ ] **Step 3: Update AppLayout to pass onOpenOverlay to Sidebar**

In the Sidebar component call within AppLayout, add:

```tsx
onOpenOverlay={(personaId) => openPersonaOverlay(personaId, "overview")}
```

- [ ] **Step 4: Verify everything compiles**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit 2>&1 | head -20`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/sidebar/PersonaItem.tsx frontend/src/app/components/sidebar/Sidebar.tsx frontend/src/app/layouts/AppLayout.tsx
git commit -m "Update sidebar with chakra colours, monogram display, and pinned persona filtering"
```

---

## Task 10: Enhanced Sanitised Mode

**Files:**
- Modify: `frontend/src/app/components/sidebar/Sidebar.tsx`
- Modify: `frontend/src/app/layouts/AppLayout.tsx`

- [ ] **Step 1: Ensure sanitised mode filters all NSFW content in sidebar**

In `frontend/src/app/layouts/AppLayout.tsx`, the existing NSFW filtering (line 25-28) already filters personas. Extend this to also filter chat sessions:

```tsx
const filteredPersonas = isSanitised
  ? personas.filter((p) => !p.nsfw)
  : personas;

// Also filter sessions — sessions linked to NSFW personas should be hidden
const nsfwPersonaIds = new Set(
  personas.filter((p) => p.nsfw).map((p) => p.id),
);
const filteredSessions = isSanitised
  ? sessions.filter((s) => !nsfwPersonaIds.has(s.persona_id))
  : sessions;
```

Pass `filteredPersonas` and `filteredSessions` to the Sidebar instead of the raw arrays.

Note: Project filtering will be added when the projects module exists. For now, persona and session filtering covers the current data model.

- [ ] **Step 2: Verify the filtering works correctly**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit 2>&1 | head -20`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/layouts/AppLayout.tsx
git commit -m "Extend sanitised mode to filter NSFW personas from chat session history"
```

---

## Task 11: Card Entrance Animation

**Files:**
- Modify: `frontend/src/app/pages/PersonasPage.tsx`
- Modify: `frontend/src/app/components/persona-card/PersonaCard.tsx`
- Modify: `frontend/src/app/components/persona-card/AddPersonaCard.tsx`

- [ ] **Step 1: Add entrance animation CSS**

Add to `frontend/src/index.css`, after the existing styles:

```css
@keyframes card-entrance {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
```

- [ ] **Step 2: Add animation to PersonaCard**

In `PersonaCard.tsx`, add an `index` prop:

```tsx
interface PersonaCardProps {
  persona: PersonaDto;
  index: number;
  onContinue: (personaId: string) => void;
  onNewChat: (personaId: string) => void;
  onOpenOverlay: (personaId: string) => void;
}
```

Add to the outer div's style:

```tsx
animation: `card-entrance 0.6s cubic-bezier(0.16, 1, 0.3, 1) ${index * 0.1}s both`,
```

- [ ] **Step 3: Add animation to AddPersonaCard**

Add an `index` prop to AddPersonaCard and apply the same staggered animation.

- [ ] **Step 4: Pass index from PersonasPage**

In `PersonasPage.tsx`, update the map to pass index:

```tsx
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
```

- [ ] **Step 5: Add hover elevation to PersonaCard**

In `PersonaCard.tsx`, the outer div already has `group` class. Add hover styles via Tailwind:

```tsx
className="group relative flex flex-col items-center rounded-3xl border cursor-grab active:cursor-grabbing
  transition-all duration-300 hover:-translate-y-2 hover:scale-[1.02]"
```

Add hover shadow via inline style using the chakra glow:

```tsx
// In the outer div's onMouseEnter/onMouseLeave or via CSS:
// Simplest: add to style object
// boxShadow on hover is handled via group-hover in Tailwind or inline
```

The agentic worker should implement this as a `hover` state with `useState` or via Tailwind `hover:` utilities, whichever integrates cleanly with the existing inline styles.

- [ ] **Step 6: Verify and commit**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit 2>&1 | head -20`
Expected: No errors

```bash
git add frontend/src/index.css frontend/src/app/components/persona-card/PersonaCard.tsx frontend/src/app/components/persona-card/AddPersonaCard.tsx frontend/src/app/pages/PersonasPage.tsx
git commit -m "Add staggered entrance animation and hover elevation to persona cards"
```

---

## Task 12: Final Integration and Smoke Test

**Files:**
- No new files — verification and minor fixes only

- [ ] **Step 1: Start the backend and verify persona CRUD with new fields**

Run: `cd /home/chris/workspace/chatsune && uv run python -m backend.main &`

Test create with new fields:
```bash
# Login first to get a token, then:
curl -X POST http://localhost:8000/api/personas \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Akira Tanaka", "tagline": "creative partner", "model_unique_id": "ollama_cloud:llama3.2", "system_prompt": "You are Akira", "colour_scheme": "crown", "pinned": true}'
```

Expected: 201 response with `monogram: "AT"`, `pinned: true`, `colour_scheme: "crown"`, `profile_image: null`.

- [ ] **Step 2: Start the frontend and verify the Personas Page renders**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm dev`

Open http://localhost:5173/personas and verify:
- Cards render with chakra colours
- Monogram badges are visible
- Drag & drop reorders cards
- Overlay opens on ⟡ button click
- Edit tab allows changes
- Add card is present

- [ ] **Step 3: Verify sanitised mode hides NSFW personas**

Create an NSFW persona, toggle sanitised mode, verify it disappears from both the page and sidebar.

- [ ] **Step 4: Fix any TypeScript or runtime errors found during testing**

Address any compilation or runtime issues found. The agentic worker should fix these inline.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "Fix integration issues from persona editor smoke test"
```

Only commit if there were actual fixes. If everything works, skip this step.
