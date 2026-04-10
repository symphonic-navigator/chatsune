# Persona Deletion — Design Spec

**Date:** 2026-04-10
**Status:** Approved

## Summary

Add the ability to permanently delete a persona and all associated data.
Deletion is triggered from the persona overlay's Overview tab and requires
two-click confirmation. No undo — aligns with the privacy-first requirement.

## Frontend

### Delete Button (OverviewTab)

- Placed at the bottom of the Overview tab, visually separated from other actions
- Styled as a subtle, red-tinted destructive button (not prominent)

### Two-Click Confirmation Flow

1. **First click:** Button text is "Delete persona". Clicking replaces the
   button with an inline warning panel:
   - Warning text: "This will permanently delete **[Name]**, all chat history,
     memories, uploads and artefacts. This cannot be undone."
   - Red "Delete permanently" button
   - "Cancel" text button to dismiss
2. **Second click:** "Delete permanently" calls `personasApi.remove(personaId)`

### Post-Deletion Behaviour

- Close the persona overlay
- Navigate to `/personas`
- Show a toast notification: "Persona deleted"
- If the user had an active chat with this persona, the navigation handles it

### State Updates

The existing `usePersonas` hook already listens for `PERSONA_DELETED` events
and removes the persona from state. No additional frontend state work needed.

## Backend

### Cascading Cleanup

The existing `DELETE /api/personas/{persona_id}` endpoint is extended to
perform cascading deletion before removing the persona itself. Each module
exposes a public `delete_by_persona(user_id, persona_id)` method — no
cross-module DB access.

Deletion order (dependencies first):

1. **Artefacts** — find all session IDs for this persona, delete artefact
   versions and artefacts for those sessions
2. **Chat sessions** — delete all messages and sessions with this `persona_id`
3. **Memory journal entries** — delete all entries with this `persona_id`
4. **Memory bodies** — delete all bodies with this `persona_id`
5. **Storage files** — delete DB records and physical files with this `persona_id`
6. **Avatar** — delete the physical avatar file if it exists
7. **Persona** — delete the persona document itself

### Module API Additions

Each module needs a bulk-delete-by-persona method in its public `__init__.py`:

| Module | New method | What it deletes |
|--------|-----------|-----------------|
| `chat` | `delete_by_persona(user_id, persona_id)` | Messages + sessions |
| `memory` | `delete_by_persona(user_id, persona_id)` | Journal entries + memory bodies |
| `storage` | `delete_by_persona(user_id, persona_id)` | DB records + physical files |
| `artefact` | `delete_by_session_ids(user_id, session_ids)` | Artefact versions + artefacts |

### Error Handling

- If any cascade step fails, the endpoint returns 500 and logs the error
- Partial cleanup is acceptable — the persona document is only deleted if
  all cascade steps succeed
- The frontend shows a generic error toast on failure

### No Soft Delete

Deliberate choice. Privacy-first means data should be gone when the user
says delete. The two-click confirmation is the safety net.

## Files to Modify

### Backend
- `backend/modules/persona/_handlers.py` — extend delete endpoint with cascade
- `backend/modules/chat/__init__.py` — expose `delete_by_persona`
- `backend/modules/chat/_repository.py` — add bulk delete methods
- `backend/modules/memory/__init__.py` — expose `delete_by_persona` (if not exists)
- `backend/modules/memory/_repository.py` — add bulk delete methods
- `backend/modules/storage/__init__.py` — expose `delete_by_persona`
- `backend/modules/storage/_repository.py` — add bulk delete + file cleanup
- `backend/modules/artefact/__init__.py` — expose `delete_by_session_ids`
- `backend/modules/artefact/_repository.py` — add bulk delete methods

### Frontend
- `frontend/src/app/components/persona-overlay/OverviewTab.tsx` — add delete UI
