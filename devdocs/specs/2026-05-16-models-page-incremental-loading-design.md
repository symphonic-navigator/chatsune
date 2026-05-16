# Models page — incremental loading

**Status:** Design  
**Date:** 2026-05-16  
**Scope:** Frontend only. No backend changes.

## Problem

The user-facing Models hub (`ModelsTab` → `ModelBrowser`) becomes
noticeably slow as more upstream providers are added. With four or more
connections (Ollama Cloud, xAI, Mistral, Novita, soon chutes.ai), users
have asked "is this broken?" because the entire page sits on a plain
"Loading models…" text until **every** upstream's model list has
returned.

The hub already issues all upstream requests in parallel
(`useEnrichedModels.ts:116-133`), but the result is committed to state
in one `setGroups(...)` call after the slowest request resolves. A
single slow provider blocks the entire render. There is also no
visual spinner — only static "Loading models…" text — so the page
appears frozen.

## Goals

- Show each provider's models **as soon as that provider responds**,
  independent of the others.
- Show **all configured providers** immediately as headers, with a
  per-group "loading" indicator, so the user can see that work is
  happening for every connection.
- Surface per-provider load failures inline (red message + retry),
  rather than silently hiding them in `console.warn`.
- Add a visible spinner during loading.

## Non-goals

- No backend changes (no new endpoint, no streaming/SSE).
- No skeleton placeholder rows with fake counts.
- No reorganisation of the filter bar or model rows.
- No changes to event-bus driven refreshes (still trigger `refresh()`).

## Design

### Data flow change in `useEnrichedModels`

Today the hook performs two sequential phases inside one `refresh()`:

1. Load connections + accounts + catalogue + user configs (parallel).
2. Load every connection's models (parallel, then `Promise.all`),
   merge, `setGroups(...)`.

We split phase 2 so each group is committed to state independently.

**Phase A — list providers.** Parallel-load connections, user configs,
catalogue, accounts (unchanged). When all four resolve, build the full
`ConnectionModelGroup[]` skeleton with `models: []` and
`status: 'loading'` for every group, and commit it.

**Phase B — per-group fetch.** For each group, fire its model-fetch
without joining the others. When a fetch resolves, update only that
group's entry (status → `'ready'`, fill `models`). When a fetch
rejects, update only that group (status → `'error'`, `error: msg`).

Concurrency is unchanged — all fetches are still in flight at the same
time. What changes is that we no longer `await Promise.all([...])` on
them; each one writes through to state on its own.

**External `loading` semantics preserved.** The hook's `loading` field
remains `true` until **every** group has reached a terminal status
(`'ready'` or `'error'`). This matches today's contract for external
consumers (`EditTab`, `OverviewTab`, `UserModal`) which use `loading`
to gate "give the hub time to resolve a specific model before showing
a missing-connection banner". The ModelBrowser itself does **not**
gate on `loading` — it uses `groups.length === 0` to decide whether
to render the phase-A placeholder, and per-group `status` for the
in-group indicators.

### Group shape

```ts
export interface ConnectionModelGroup {
  connection: Connection
  models: EnrichedModelDto[]
  status: 'loading' | 'ready' | 'error'
  error?: string
}
```

`status === 'loading'` is the initial value for every group during
phase A and again whenever a per-group retry runs.

### Refresh semantics

- Full `refresh()` (initial mount, event-bus triggers): re-runs phase
  A, which resets every group to `'loading'`, then phase B writes
  each group through as it finishes. This matches today's behaviour
  from the user's perspective — the page refreshes — and keeps the
  event-bus subscriptions in `useEnrichedModels.ts:178-191` working
  without changes.
- Per-group retry (the existing `⟳` button on a group header): no
  change to the API call (`llmApi.refreshConnectionModels` /
  `providersApi.refreshProviderModels` already exist). After the
  server-side refresh completes, the event-bus emits
  `LLM_CONNECTION_MODELS_REFRESHED` /
  `PREMIUM_PROVIDER_MODELS_REFRESHED`, which triggers `refresh()` —
  unchanged from today.

### UI changes in `ModelBrowser.tsx`

- Remove the top-level "Loading models…" branch
  (`ModelBrowser.tsx:79-81`). Instead use `groups.length === 0 && !error`
  during phase A to render a minimal placeholder. Once phase A
  commits, the normal grouped list renders with per-group loaders
  inside.
- The "No LLM connection configured" empty state
  (`ModelBrowser.tsx:98-104`) stays as-is — it only triggers when
  phase A returns zero groups.
- `filteredGroups` (lines 54-70) needs one tweak: groups with
  `status === 'loading'` or `'error'` must remain visible even when
  `models.length === 0`. Today the filter keeps empty groups only if
  the **source** was empty, which is the right behaviour for the
  "ready but empty" case. We extend it to also keep loading/error
  groups.

### UI changes in `ConnectionGroup`

Three render branches inside the group body, replacing the current
"models.length === 0 ? empty-hint : list":

- `status === 'loading'` →
  `<div class="...">⟳ Lädt Modelle…</div>` (small spinner, muted text).
- `status === 'error'` →
  red one-liner with the error message and a hint that the `⟳`
  button retries.
- `status === 'ready'` and `models.length === 0` → existing "No models
  listed for this connection yet. Click ⟳…" hint.
- `status === 'ready'` and `models.length > 0` → existing list.

The group header itself (display name, slug, collapse toggle,
refresh button) is unchanged. The existing `refreshing` local state
on `ConnectionGroup` (lines 244-269) stays — it controls the header
button's spin animation during the explicit user-triggered refresh
and is independent of the new group `status` field.

### Spinner

A small CSS-only spinner via Tailwind:
`<span class="inline-block h-3 w-3 animate-spin rounded-full border-2 border-white/30 border-t-white/80" />`.
No new asset, no library. Used inside the loading branch of
`ConnectionGroup`. The existing header `⟳` button's `animate-pulse`
stays — different visual purpose (user-initiated refresh on a known
group) so it does not need to match.

### Premium pseudo-connections

Handled identically. Each premium account is a group with the same
`status` field, fetched via `providersApi.listProviderModels(slug)`.
The synthetic `created_at = epoch` ordering already places premium
groups ahead of user connections — unchanged.

### Filter bar during phase A

Phase A's placeholder is brief (the four header-only API calls in
parallel). To keep the design simple we hide the filter bar during
phase A and render it once groups are present. This avoids a flicker
where the provider dropdown is empty for a beat. Search, billing
filter, etc. are not useful before any group exists anyway.

## Files affected

- `frontend/src/core/hooks/useEnrichedModels.ts` — restructure
  `refresh()` into phases A and B; extend `ConnectionModelGroup` with
  `status` and `error`; change state-update strategy to per-group
  updates in phase B.
- `frontend/src/app/components/model-browser/ModelBrowser.tsx` —
  remove top-level loading branch; pass `status`/`error` to
  `ConnectionGroup`; adjust the `filteredGroups` keep-if rule;
  conditionally render filter bar.
- `frontend/src/app/components/model-browser/__tests__/ModelBrowser.test.tsx`
  — update for the new loading flow; mocks may need per-group resolve
  control (e.g. deferred promises) to assert that one group renders
  while another is still loading.

No backend, no shared/, no event-bus changes.

## Testing

- Existing component tests for the Models page continue to pass.
- New test: with two mocked connections where one resolves
  immediately and the other is held, the first group's models render
  while the second still shows the loading state.
- New test: when one group's fetch rejects, that group shows the
  error message; siblings remain unaffected.
- Manual: run with all configured providers; observe that fast
  providers (e.g. Mistral) render before slow ones (e.g. an Ollama
  Cloud experiencing latency).

## Risks / open questions

- **Stale writes after re-mount or successive `refresh()` calls.**
  If `refresh()` is invoked twice in quick succession, in-flight
  fetches from the first call could resolve after the second call has
  reset state, overwriting fresh data with stale. We guard with a
  monotonically-incrementing "generation" counter inside the hook:
  each `refresh()` bumps it; per-group resolvers compare against the
  current generation before writing, and drop the write if it is
  stale. This is a small but necessary piece of bookkeeping.
- **Event-bus storm.** When many `LLM_CONNECTION_MODELS_REFRESHED`
  events arrive in quick succession (e.g. user refreshes all
  providers in a row), every event currently triggers a full
  `refresh()`. With the new flow that is more visible — every event
  resets every group to `'loading'` briefly. If this becomes a
  problem we add per-event scoping (only refetch the affected
  connection's models), but that is **out of scope** for this spec —
  call it out, do not preemptively build it.

## Out of scope (deferred)

- Per-event scoped refreshes (only refetch the affected provider when
  an event names it).
- Skeleton placeholder rows.
- Cache-warm / stale-while-revalidate behaviour where last-known
  models render instantly and refresh in background.
