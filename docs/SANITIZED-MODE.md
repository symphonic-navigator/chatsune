# Sanitised Mode

## Overview

Sanitised mode is a client-side content filter that hides NSFW-flagged content
from the UI. It is designed for situations where the user wants to use or
demonstrate Chatsune in a professional or public setting.

## Key Principles

- **Client-side only** — the toggle state is stored in `localStorage`, never in the
  database. This ensures switching is instant and leaves no server-side trace.
- **Per-browser persistence** — opening Chatsune on a work laptop defaults to the
  last-used setting on that browser. A different browser starts fresh (sanitised off).
- **Scope grows over time** — initially only personas carry an `nsfw` flag, but
  the mechanism is designed to extend to knowledge libraries, projects, chat
  sessions, uploads, and artefacts.

## What Gets the NSFW Flag

| Entity            | Phase | How it gets flagged                               |
|-------------------|-------|---------------------------------------------------|
| Persona           | 1     | Manual toggle when creating/editing a persona      |
| Knowledge library | later | Manual toggle on the library                       |
| Project           | later | Manual toggle on the project                       |
| Chat session      | later | Inherits from persona (`nsfw` persona = `nsfw` session) |
| Upload            | later | Inherits from the context it was uploaded in       |
| Artefact          | later | Inherits from the context it was created in        |

## Behaviour When Sanitised Mode Is On

- NSFW personas are **hidden** from the sidebar and persona list
- NSFW chat sessions are **hidden** from history
- NSFW knowledge libraries, projects, uploads, and artefacts are **hidden**
  from their respective views (when implemented)
- Navigation to an NSFW entity via direct URL **redirects** to the home view
- The UI gives **no indication** that hidden content exists — it simply does not
  appear

## Behaviour When Sanitised Mode Is Off

Everything is visible. No filtering applied.

## UI Toggle

The toggle lives in the sidebar, between the bottom navigation section and the
user profile row. It uses a padlock icon:

- **Sanitised ON:** coloured padlock (locked) — NSFW content hidden
- **Sanitised OFF:** grey padlock (unlocked) — everything visible

Clicking the icon toggles the state immediately. All views re-render reactively
via a Zustand store.

## Storage

- Key: `chatsune_sanitised_mode`
- Values: `"true"` / `"false"`
- Default (no key present): `false` (sanitised off — show everything)

## Technical Details

- Zustand store: `useSanitisedMode` in `frontend/src/core/store/sanitisedModeStore.ts`
- The store exposes `isSanitised` (boolean) and `toggle()` (function)
- Filtering happens in the consuming components, not in the store — the store
  is purely a state holder
- The `usePersonas` hook (and later other hooks) filters based on the store value
