# API-Keys Management — Design Spec

## Overview

Add a user-facing API-Keys tab to the User Modal, allowing users to manage their
upstream provider API keys. Keys are essential for operation — the UI must surface
missing or broken keys prominently so users are never left wondering why inference
stopped working.

## Requirements

### Functional

1. **API-Keys Tab** in the User Modal as the last tab entry
2. **Dynamic provider list** — all providers from `GET /api/llm/providers` (populated
   from `ADAPTER_REGISTRY`), no hardcoded provider names
3. **Key lifecycle:** set, edit, test, delete
4. **Auto-test on save** — saving a key immediately triggers a connectivity test
5. **Manual re-test** — users can re-test a saved key without changing it
6. **Delete with 2-step confirm** — same pattern as admin user deletion
7. **Key masking** — saved keys displayed as dots, never returned from the API

### Warning System

**Problem state** is defined as:
- No key is configured for any provider, OR
- At least one configured key has status `failed`

Note: a provider with no key configured does NOT count as failed. The user may
choose to only use a subset of available providers. The problem arises when either
nothing is configured at all or something that IS configured is broken.

**When problem state is active:**
- Warning indicator (!) on the "API-Keys" tab label in the User Modal tab bar
- Once per session: User Modal auto-opens on the API-Keys tab on first page load
- Clicking the user avatar in the sidebar opens the API-Keys tab instead of About Me

**When no problem:** Normal behaviour — no warning, avatar opens About Me.

### Non-Requirements

- No backend changes needed — all endpoints already exist
- No new shared DTOs needed — `ProviderCredentialDto` already covers the response shape
- No WebSocket events for key changes (REST-only workflow, user-scoped)

## UI Design

### Tab Placement

Last tab in the User Modal tab bar, after "settings". Label: "api-keys".
When problem state is active, the label gets a warning indicator.

### Table Layout

| Column   | Content                                          |
|----------|--------------------------------------------------|
| PROVIDER | Provider display name from the API               |
| KEY      | Masked dots or "not configured" (italic, dimmed)  |
| STATUS   | Badge: VERIFIED (green), FAILED (red), TESTING (yellow), or dash |
| OPS      | Action buttons: SET/EDIT, TEST, DEL              |

### Row States

**Configured + Verified:**
- Provider name at normal opacity
- Key shown as `••••••••••••`
- Green VERIFIED badge
- OPS: EDIT, TEST, DEL buttons

**Configured + Failed:**
- Subtle red background tint on the row
- Red FAILED badge
- OPS: EDIT, TEST, DEL buttons

**Configured + Testing:**
- Yellow TESTING badge with spinner
- OPS: buttons disabled during test

**Not configured:**
- Provider name at reduced opacity
- "not configured" in italic, dimmed text
- No status badge (dash)
- OPS: gold SET button only

### Inline Expansion (Edit Mode)

Triggered by SET or EDIT button. Expands a row below the provider entry:

- Password input field with visibility toggle (eye icon)
- SAVE button (gold accent, disabled when input is empty)
- CANCEL button (neutral)
- Helper text: "Saving will automatically run a connectivity test"
- If the key previously failed: last error message shown in red
- Keyboard: Enter = Save, Escape = Cancel

### Delete Flow

DEL button uses 2-step confirmation (same pattern as admin UsersTab):
1. First click: button changes to "SURE?" with red styling
2. Second click: executes deletion
3. Reverts after a short timeout if not confirmed

## State Management

### Session-Level Warning Tracking

A simple boolean flag (React ref or Zustand) tracks whether the auto-open has
fired this session. Set to `true` after the first auto-open. Reset only on
full page reload or new login.

### Provider Status Fetching

On tab mount, fetch `GET /api/llm/providers` to get the current list with
`is_configured` status. For configured providers, the `created_at` field
indicates when the key was set (test status comes from the provider list response).

### Problem State Derivation

```
hasApiKeyProblem = (
  no provider has is_configured === true
  OR
  any provider with is_configured === true has test status "failed"
)
```

This is computed from the providers list response. It needs to be available to:
- `UserModal.tsx` (tab warning indicator)
- `AppLayout.tsx` (auto-open logic)
- `Sidebar.tsx` (avatar click target)

Approach: fetch providers on app mount (after auth), store result in a shared
location (Zustand store or context). Re-fetch after any key set/delete/test
operation.

## Files to Create/Modify

### New Files

| File | Purpose |
|------|---------|
| `frontend/src/app/components/user-modal/ApiKeysTab.tsx` | Main tab component |

### Modified Files

| File | Change |
|------|--------|
| `frontend/src/app/components/user-modal/UserModal.tsx` | Add api-keys tab entry |
| `frontend/src/app/layouts/AppLayout.tsx` | Auto-open logic on problem state |
| `frontend/src/app/components/sidebar/Sidebar.tsx` | Conditional avatar click target |
| `frontend/src/core/api/llm.ts` | Add missing API client functions if needed (set key, test key, delete key) |

### Backend

No changes required. Existing endpoints:
- `GET /api/llm/providers` — list providers with credential status
- `PUT /api/llm/providers/{provider_id}/key` — set/update key
- `POST /api/llm/providers/{provider_id}/test` — test key
- `DELETE /api/llm/providers/{provider_id}/key` — delete key

## Styling

Follows existing Chatsune design system:
- Table styling matches admin UsersTab (header: `text-[10px] uppercase tracking-wider`,
  rows: `border-b border-white/6`, hover: `hover:bg-white/4`)
- Status badges match existing patterns (green/red/yellow with border + bg opacity)
- Gold accent for primary actions (SET, SAVE)
- Input styling: `bg-white/[0.03] border border-white/10 focus:border-gold/30`
- 2-step delete confirm matches admin pattern
