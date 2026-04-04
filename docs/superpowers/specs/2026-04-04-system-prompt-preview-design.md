# System Prompt Preview on Persona Overview

**Date:** 2026-04-04
**Status:** Draft
**Scope:** Last feature before chat implementation

---

## Goal

Give users a glanceable preview of the fully assembled system prompt directly
in the persona's Overview tab. This helps users understand what the LLM
actually sees, encourages them to refine their persona setup, and reinforces
the tight coupling between persona and model.

## Design Decisions

- **Persona + Model are married:** A persona's `model_unique_id` is the only
  model context needed. Cross-model portability is not a goal.
- **Single Source of Truth:** The backend's existing `assemble_preview()` does
  the assembly and sanitisation. The frontend receives a ready-to-render string.
- **No new DTO:** The endpoint returns a plain `{ "preview": "..." }` object.
  The format is human-readable text with `--- Section ---` headers, not
  structured data -- the frontend renders it as-is.

---

## Backend

### New Endpoint

**`GET /api/personas/{persona_id}/system-prompt-preview`**

- **Auth:** Required. User ID from JWT.
- **Logic:**
  1. Fetch persona by ID + user ownership check (reuse existing `get_persona`)
  2. Read `model_unique_id` from the persona document
  3. Call `assemble_preview(user_id, persona_id, model_unique_id)`
  4. Return `{ "preview": "<assembled text>" }`
- **Responses:**
  - `200` with preview text (may be empty string if nothing configured)
  - `404` if persona not found or not owned by user
- **Location:** `backend/modules/persona/_handlers.py`

### Export Change

`backend/modules/chat/__init__.py` must re-export `assemble_preview` from
`_prompt_assembler` so the persona module can import it cleanly:

```python
from backend.modules.chat import assemble_preview
```

This is a cross-module call through the public API -- no boundary violation.

---

## Frontend

### Location

`frontend/src/app/components/persona-overlay/OverviewTab.tsx`

No new component file. The OverviewTab is currently 83 lines and will stay
well under 150 with the addition.

### Placement

Below the stats grid, above the created-date line.

### Collapsed State (default)

- Monospace text (`'Courier New', monospace`), 12px
- Maximum ~3 visible lines, then a fade-out gradient to the background
- Text colour: `white/50` (dezent but readable)
- Section headers (`--- Persona ---`, etc.) rendered in the persona's
  chakra colour
- Below the fade: a small text button "Show full prompt" in `white/35`

### Expanded State

- Same monospace styling, full height revealed
- `max-height` CSS transition for smooth expand/collapse
- Scrollable if content exceeds ~60vh
- Button text changes to "Collapse"

### Empty State

- If `assemble_preview` returns an empty string, the entire section is
  hidden. No "nothing configured" placeholder.

### Fetch Behaviour

- Single `GET` call on OverviewTab mount
- Simple loading state (section invisible until loaded, no skeleton)
- No refetch while tab remains open

---

## Files Changed

| File | Change |
|------|--------|
| `backend/modules/chat/__init__.py` | Re-export `assemble_preview` |
| `backend/modules/persona/_handlers.py` | New endpoint (~15 lines) |
| `frontend/src/app/components/persona-overlay/OverviewTab.tsx` | Inline preview section with expand/collapse |

### Not Changed

- `_prompt_assembler.py` -- logic already exists
- `_prompt_sanitiser.py` -- already called by `assemble_preview`
- `shared/dtos/` -- no new DTO needed
- WebSocket / event routing -- pure REST

---

## Out of Scope

- System prompt preview in the chat view (separate feature, later)
- Editable prompt from the overview (the Edit tab handles that)
- Cache prefix optimisation (stable as long as user does not change config)
