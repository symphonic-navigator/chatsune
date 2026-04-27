# Persona "Use Memory" Toggle — Design

**Date:** 2026-04-27
**Status:** Approved (pending implementation plan)

## Motivation

Some personas are used for casual, unconnected storytelling — for example a
persona that generates one-off short stories where today's narrative has
nothing to do with yesterday's. Injecting accumulated memory and journal
entries into the prompt is actively harmful in that case: the model
attempts to thread continuity through stories that are intentionally
disjoint.

Users need a switch to opt out of memory **injection** for such personas.

A naïve "disable memory entirely" switch is dangerous: if a user runs a
persona for weeks with the switch off and then flips it on, the
consolidation pipeline would suddenly process thousands of accumulated
messages and overwhelm the job engine. Generation must therefore continue
in the background even when injection is disabled — only the prompt-time
read path is gated.

## Scope

**In scope:**
- New persona-level boolean `use_memory` (default `true`).
- Editor toggle on the persona Edit tab, placed directly below the
  existing NSFW toggle.
- Gate the persona-scoped memory block in the chat prompt assembler.
- Persisting and round-tripping the field through the persona create /
  update / read DTOs.

**Out of scope:**
- About-me (`<userinfo>`) injection — stays unconditional. Users rely on
  about-me for global preferences (e.g. "speak to me in the language I
  opened the conversation in"), which must apply to every persona
  regardless of this toggle.
- Model instructions, integration prompt extensions, system prompt — all
  unaffected.
- Memory generation pipeline — consolidation jobs, journal extraction,
  embeddings continue running unchanged.
- The Memories tab in the persona overlay — remains visible and
  interactive, since memories are still being collected.
- Migration script — backwards-compatible read defaults make a one-shot
  migration unnecessary.

## Architecture

### Data model

Add `use_memory: bool = True` to:

- `backend/modules/persona/_models.py` → `PersonaDocument`
- `shared/dtos/persona.py` → `PersonaDto`, `CreatePersonaDto`,
  `UpdatePersonaDto` (the latter as `bool | None = None` consistent with
  every other update field)

The Pydantic default of `True` handles the upgrade path: existing persona
documents that lack the field deserialise cleanly with `use_memory=True`,
matching today's behaviour. No migration is required. This is the
"backwards-compatible reads are the default" path mandated by CLAUDE.md.

`CreatePersonaDto.use_memory: bool = True` is technically redundant
(matches the document default) but is retained for API symmetry with
`nsfw`, which sits next to it.

### Gate point

`backend/modules/chat/_prompt_assembler.py`, currently lines 108–112:

```python
# Layer: User memory (if available)
from backend.modules.memory import get_memory_context
memory_xml = await get_memory_context(user_id, persona_id) if persona_id else None
if memory_xml:
    parts.append(memory_xml)
```

becomes:

```python
# Layer: User memory (if available, and the persona opts in to injection)
use_memory = bool(persona_doc.get("use_memory", True)) if persona_doc else True
if persona_id and use_memory:
    from backend.modules.memory import get_memory_context
    memory_xml = await get_memory_context(user_id, persona_id)
    if memory_xml:
        parts.append(memory_xml)
```

The `persona_doc` is already loaded earlier in `assemble` (line 75 today,
via `_get_persona_doc`) for the soft-CoT lookup, so no additional database
round-trip is introduced.

`assemble_preview` (the same file, lines 158+) does not include memory
today and therefore needs no change.

### Frontend

`frontend/src/core/types/persona.ts`:
- Add `use_memory: boolean` to the read-shape `PersonaDto`.
- Add `use_memory?: boolean` to the create / update shapes.

`frontend/src/app/components/persona-overlay/EditTab.tsx`:
- New local state `const [useMemory, setUseMemory] = useState(persona.use_memory)`.
- Add `useMemory !== persona.use_memory` to the `isDirty` expression.
- Add `use_memory: useMemory` to the `handleSave` payload.
- Render a new `<Toggle>` immediately after the NSFW toggle (currently
  the last entry in the Toggles section) with:
  - Label: `Use memory`
  - Description: `Inject this persona's memories into the prompt. Memories are still generated when off.`

`frontend/src/app/components/persona-overlay/PersonaOverlay.tsx`:
- Add `use_memory: true` to the `emptyPersona` literal so the create form
  starts in the on-state.

### Module boundaries

No module boundary is crossed. The chat module already reads the persona
document via the persona module's public `get_persona` API; this design
just adds one more field to the document it consumes. The memory module
stays unaware of the toggle entirely — it continues to do whatever the
job engine schedules.

## Manual verification

To be carried out on a real, non-empty persona before merging:

1. **Default-on backwards compatibility.** Open an existing persona
   (created before this change). The "Use memory" toggle is rendered in
   the on-state. Sending a message produces a prompt that contains the
   `<memory>` block (verifiable via the dev preview or backend logs).
2. **Toggle off, no injection.** Switch the toggle off, save, send a
   message. The assembled prompt no longer contains a `<memory>` block.
   The `<userinfo>` block (about-me) is still present and unchanged.
3. **Generation still runs while off.** With the toggle off, send several
   substantive messages and wait for the consolidation job to fire (or
   trigger it manually if a debug entry-point exists). Open the
   Memories tab — new entries appear.
4. **Re-enabling picks up backlog.** Toggle the switch back on, send the
   next message. The `<memory>` block reappears in the prompt and now
   includes the entries that accumulated during step 3.
5. **About-me independence.** With the toggle off, set or change the
   user-level about-me text. The next message's prompt reflects the new
   about-me regardless of the toggle's state.
6. **New persona create.** Create a new persona via the Edit tab. The
   "Use memory" toggle starts in the on-state. The persisted persona
   document round-trips with `use_memory: true`.

## What this design deliberately does not change

- No new event types, no Redis-stream traffic — `use_memory` rides along
  with the existing persona update/read DTOs and reaches the frontend
  through the same `personas` API surface.
- No tests are added for the toggle's wiring on the model layer; the
  manual verification above plus the existing persona DTO tests cover
  the behaviour.
- No analytics / audit log entry for flipping the toggle. If that is
  later wanted, it can be added without re-touching the gate logic.
