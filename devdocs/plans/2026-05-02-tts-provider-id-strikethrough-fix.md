# TTS Provider ID Strikethrough Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the "Voice chat" strikethrough that appears in the chat top bar for personas with a configured TTS voice but no explicit `voice_config.tts_provider_id`, by aligning the top-bar gate with the cockpit gate, persisting the implicit default on save, and back-filling existing persona documents.

**Architecture:** Three coordinated changes:
- **(A)** `useVoiceAvailable` (top-bar gate) gains the same TTS-integration fallback the cockpit gate already uses, so an unset `tts_provider_id` falls back to the first enabled TTS integration before checking the Premium Provider Account.
- **(B)** `PersonaVoiceConfig.persistVoiceConfig` writes the resolved (default) `tts_provider_id` on every save, so newly created personas can never end up with `voice_config` missing the field.
- **(C)** A one-shot startup migration backfills `voice_config.tts_provider_id` on existing persona documents that have a configured voice but no provider id.

**Tech Stack:** TypeScript + React + Vitest (frontend), Python + FastAPI + pytest + Motor/MongoDB (backend).

---

## Background

**Symptom:** Persona "test2" with `mistral_voice` selected (and a working Mistral Premium Provider Account) shows a struck-through "VOICE CHAT" pill in the chat top bar. Switching the persona to xAI voice clears the strikethrough; switching back to Mistral does *not* re-introduce it once the side-effect of the toggle has written `voice_config.tts_provider_id`.

**Root cause (verified against MongoDB on 2026-05-02):**
- Persona "test2" has `integration_configs.mistral_voice.voice_id = "<uuid>"` but **no `voice_config` field at all**.
- The cockpit Live-button gate (`resolveTTSEngine` in `frontend/src/features/voice/engines/resolver.ts:34-49`) has a documented fallback to `firstEnabledIntegrationId(TTS_CAP)` when `voice_config.tts_provider_id` is unset → recognises Mistral → button works.
- The top-bar `useVoiceAvailable` (`frontend/src/features/voice/components/ConversationModeButton.tsx:40-72`) has **no fallback**: `if (!ttsProviderId) return false` → strikethrough.
- The `<select>` in `PersonaVoiceConfig.tsx:204-217` displays the first provider with the suffix "(default)" but only persists `tts_provider_id` when the user actively changes the selection. A persona that is created and only has its voice picked never writes `tts_provider_id`.

The DTO comment in `shared/dtos/persona.py:32-36` explicitly documents the intended semantics: `tts_provider_id = None` means "use the first enabled TTS provider — the resolver applies the fallback." `useVoiceAvailable` violates this contract.

---

## File Structure

| Path | Role | Change |
|---|---|---|
| `frontend/src/features/voice/engines/resolver.ts` | TTS/STT engine resolution | Export the existing `firstEnabledIntegrationId` and `TTS_CAP` so other modules can apply the same fallback. |
| `frontend/src/features/voice/components/ConversationModeButton.tsx` | Top-bar voice-chat pill | `useVoiceAvailable` gains the fallback; subscribes to `useIntegrationsStore` for reactivity. |
| `frontend/src/features/voice/components/ConversationModeButton.test.tsx` | Vitest suite | Add regression test for the unset-`tts_provider_id` + configured-Mistral-account case. |
| `frontend/src/features/voice/components/PersonaVoiceConfig.tsx` | Persona voice editor | `persistVoiceConfig` writes the resolved default `tts_provider_id` when prior is null. |
| `frontend/src/features/voice/components/PersonaVoiceConfig.test.tsx` | Vitest suite (NEW) | Test that the implicit default is persisted on first save. |
| `backend/modules/persona/_migration_tts_provider_id.py` | One-shot startup migration (NEW) | Backfill `voice_config.tts_provider_id` for personas that have a voice but no provider id. |
| `backend/main.py` | Startup lifespan | Call `run_if_needed` for the new migration. |
| `backend/tests/modules/persona/__init__.py` | Test package marker (NEW) | Empty file. |
| `backend/tests/modules/persona/test_migration_tts_provider_id.py` | pytest suite (NEW) | Pure-function test of `pick_default_provider_id` (no DB). |

Conventions to honour:
- British English in code, comments, docs.
- Module boundaries: the migration lives under `backend/modules/persona/` (not `backend/migrations/`) because it modifies the `personas` collection and follows the inline-startup-with-marker pattern from `backend/modules/providers/_migration_v1.py`.

---

## Task 1: Export `firstEnabledIntegrationId` from the resolver

**Why first:** Task 2 imports it. Doing this in isolation makes the change visible and reviewable.

**Files:**
- Modify: `frontend/src/features/voice/engines/resolver.ts`

- [ ] **Step 1: Read the current resolver to see what already exists.**

The functions `firstEnabledIntegrationId(cap: string)` and the constant `TTS_CAP = 'tts_provider'` already live in `resolver.ts:11,14-21`. They are file-private. Make them named exports so other modules can re-use the exact same fallback logic.

- [ ] **Step 2: Edit `resolver.ts` — add `export` to both.**

Change line 11 from:

```typescript
const TTS_CAP = 'tts_provider'
```

to:

```typescript
export const TTS_CAP = 'tts_provider'
```

Change line 14 from:

```typescript
function firstEnabledIntegrationId(cap: string): string | undefined {
```

to:

```typescript
export function firstEnabledIntegrationId(cap: string): string | undefined {
```

(`STT_CAP` may stay private — Task 1 only needs the TTS pieces.)

- [ ] **Step 3: Verify the build still typechecks.**

Run from the repo root:

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: no errors. (No call sites change yet.)

- [ ] **Step 4: Commit.**

```bash
git add frontend/src/features/voice/engines/resolver.ts
git commit -m "Export firstEnabledIntegrationId and TTS_CAP from voice resolver"
```

---

## Task 2: Top-bar gate parity — `useVoiceAvailable` learns the fallback

**Files:**
- Modify: `frontend/src/features/voice/components/ConversationModeButton.tsx`
- Test: `frontend/src/features/voice/components/ConversationModeButton.test.tsx`

- [ ] **Step 1: Write the failing regression test.**

Open `frontend/src/features/voice/components/ConversationModeButton.test.tsx`. Add the following import near the top with the other imports:

```typescript
import { useIntegrationsStore } from '../../integrations/store'
```

Then add the following test inside the existing `describe('ConversationModeButton', ...)` block (after the existing "is not strikethrough" regression test, before the `describe('paused lifecycle', ...)` block).

The test mirrors the production bug: persona has `tts_provider_id` unset, but `mistral_voice` is the first enabled TTS integration and a Mistral Premium Provider Account is configured.

```typescript
  // Regression test for the test2-persona bug (2026-05-02): a persona that
  // has its voice configured but voice_config.tts_provider_id unset must not
  // render the strikethrough as long as the resolver's fallback (first enabled
  // TTS integration) maps to a configured Premium Provider Account. Mirrors
  // the cockpit Live-button gate.
  it('is not strikethrough when tts_provider_id is unset but the fallback TTS integration has a configured premium account', () => {
    useIntegrationsStore.setState({
      definitions: [
        {
          id: 'mistral_voice',
          capabilities: ['tts_provider'],
        } as never,
      ],
      configs: {
        mistral_voice: { effective_enabled: true } as never,
      },
    })
    useProvidersStore.setState({
      accounts: [
        {
          provider_id: 'mistral',
          config: {},
          last_test_status: 'ok',
          last_test_error: null,
          last_test_at: null,
        },
      ],
      catalogue: [],
    })
    render(
      <ConversationModeButton
        persona={{ id: 'p1', voice_config: { tts_provider_id: null } }}
      />,
    )
    const btn = screen.getByRole('button')
    expect(btn.style.textDecoration).not.toContain('line-through')
    expect(btn).not.toBeDisabled()
    expect(btn.getAttribute('aria-label')).toBe('Start conversational mode')
  })
```

- [ ] **Step 2: Run the test and confirm it fails.**

```bash
cd frontend && pnpm vitest run src/features/voice/components/ConversationModeButton.test.tsx
```

Expected: the new test fails because `useVoiceAvailable` returns `false` for an unset `tts_provider_id`. The other tests must continue to pass.

- [ ] **Step 3: Modify `ConversationModeButton.tsx` — import the resolver helpers.**

In `frontend/src/features/voice/components/ConversationModeButton.tsx`, add to the imports section near the top of the file:

```typescript
import { firstEnabledIntegrationId, TTS_CAP } from '../engines/resolver'
import { useIntegrationsStore } from '../../integrations/store'
```

- [ ] **Step 4: Modify `useVoiceAvailable` to apply the fallback and subscribe to the integrations store.**

Replace the body of `useVoiceAvailable` (currently lines 40-72) with:

```typescript
function useVoiceAvailable(persona: PersonaVoiceShape | null | undefined): boolean {
  // Select the stable `accounts` array rather than the derived Set — the
  // latter is a new object every render and causes a re-render loop.
  const accounts = useProvidersStore((s) => s.accounts)
  const hydrated = useProvidersStore((s) => s.hydrated)
  const loading = useProvidersStore((s) => s.loading)
  const error = useProvidersStore((s) => s.error)
  const refresh = useProvidersStore((s) => s.refresh)
  // Subscribe to the integrations store so a toggle of mistral_voice /
  // xai_voice immediately re-renders this component. firstEnabledIntegrationId
  // reads from the same store via getState() but reading via a selector here
  // is what wires the React subscription.
  useIntegrationsStore((s) => s.definitions)
  useIntegrationsStore((s) => s.configs)

  // Lazy hydrate: if no consumer has loaded the providers store yet (e.g.
  // the user hasn't opened the User-Modal since the app booted), the button
  // would otherwise show as unavailable until the modal is opened. Trigger
  // a one-off refresh on first mount; the `hydrated` flag prevents retries
  // when the account list is genuinely empty.
  useEffect(() => {
    if (!hydrated && !loading && error === null) void refresh()
  }, [hydrated, loading, error, refresh])

  // Mirror the cockpit Live-button gate: the persona's explicit
  // tts_provider_id wins, but if it is null/undefined we fall back to the
  // first enabled TTS integration, exactly like resolveTTSIntegrationId does
  // (see voice/engines/resolver.ts). This keeps the two gates from diverging.
  const explicitTtsId = persona?.voice_config?.tts_provider_id ?? undefined
  const effectiveTtsId = explicitTtsId ?? firstEnabledIntegrationId(TTS_CAP)
  if (!effectiveTtsId) return false

  const ttsPremium = providerIdForIntegration(effectiveTtsId)
  // If the resolved TTS integration is not premium-linked (e.g. a local
  // engine), we treat it as available — the legacy `available` prop path
  // still gates further downstream.
  if (!ttsPremium) return true
  const configuredIds = new Set(accounts.map((a) => a.provider_id))
  if (!configuredIds.has(ttsPremium)) return false
  // NOTE: no STT gate here. STT is a user-level setting living in
  // `useVoiceSettingsStore` (see `stt_provider_id` there), not a
  // persona-level field. Mixing the two concerns here was the cause of
  // the original drift; the user-level STT readiness check lives in the
  // voice engines resolver.
  return true
}
```

Also update the JSDoc block above the function (lines 19-39 in the original file) — the "IMPORTANT: tts_provider_id is nested under voice_config" warning is still valid, but the new behaviour deserves a note:

Replace:

```typescript
/**
 * True when every voice integration the persona is bound to has a
 * configured Premium Provider Account. A missing `tts_provider_id`
 * falls through to `false` because without a TTS provider, voice chat
 * cannot produce output.
 */
```

with:

```typescript
/**
 * True when the persona's effective TTS integration has a configured
 * Premium Provider Account. The effective integration is the persona's
 * explicit `voice_config.tts_provider_id` if set, otherwise the first
 * enabled TTS integration (mirroring the cockpit Live-button gate via
 * resolveTTSIntegrationId in voice/engines/resolver.ts).
 */
```

- [ ] **Step 5: Run the full ConversationModeButton suite.**

```bash
cd frontend && pnpm vitest run src/features/voice/components/ConversationModeButton.test.tsx
```

Expected: all tests pass, including the new one.

- [ ] **Step 6: Run the resolver test suite to make sure the export change has not regressed it.**

```bash
cd frontend && pnpm vitest run src/features/voice/engines
```

Expected: all tests pass.

- [ ] **Step 7: Frontend full build.**

```bash
cd frontend && pnpm run build
```

Expected: clean build — `pnpm run build` covers the strict `tsc -b` checks that `pnpm tsc --noEmit` does not (per `MEMORY.md → feedback_frontend_build_check`).

- [ ] **Step 8: Commit.**

```bash
git add \
  frontend/src/features/voice/components/ConversationModeButton.tsx \
  frontend/src/features/voice/components/ConversationModeButton.test.tsx
git commit -m "Align top-bar voice-chat gate with cockpit fallback for unset tts_provider_id"
```

---

## Task 3: Persist the implicit default `tts_provider_id` on save

**Files:**
- Modify: `frontend/src/features/voice/components/PersonaVoiceConfig.tsx`
- Test (NEW): `frontend/src/features/voice/components/PersonaVoiceConfig.test.tsx`

**Goal:** When the user is on the persona voice editor and the editor is using the implicit default TTS provider (no explicit choice persisted yet), any save (modulation slider, narrator-mode change, voice-id change) must write `tts_provider_id = activeTTS.id` rather than `null`.

- [ ] **Step 1: Write the failing test.**

Create `frontend/src/features/voice/components/PersonaVoiceConfig.test.tsx`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { PersonaVoiceConfig } from './PersonaVoiceConfig'
import { useIntegrationsStore } from '../../integrations/store'

// Minimal persona that satisfies the props shape used by PersonaVoiceConfig.
function makePersona(overrides: Record<string, unknown> = {}) {
  return {
    id: 'p-test',
    name: 'test',
    voice_config: null,
    integration_configs: {
      mistral_voice: { voice_id: 'v-1' },
    },
    ...overrides,
  } as never
}

describe('PersonaVoiceConfig', () => {
  beforeEach(() => {
    useIntegrationsStore.setState({
      definitions: [
        {
          id: 'mistral_voice',
          display_name: 'Mistral',
          capabilities: ['tts_provider'],
        } as never,
      ],
      configs: {
        mistral_voice: { effective_enabled: true } as never,
      },
    })
  })

  it('persists the implicit default tts_provider_id when the user changes the narrator mode without ever touching the provider selector', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined)
    render(
      <PersonaVoiceConfig
        persona={makePersona()}
        onSave={onSave}
        playPreview={vi.fn()}
      />,
    )
    // The narrator-mode select is the simplest persistVoiceConfig trigger we
    // can drive without VoiceFormWithPreview side effects. It has no
    // aria-label in production, so we identify it by its option set
    // (off / play / narrate) which is unique within the rendered tree.
    const selects = screen.getAllByRole('combobox') as HTMLSelectElement[]
    const narratorSelect = selects.find(
      (s) =>
        s.querySelector('option[value="off"]') &&
        s.querySelector('option[value="play"]') &&
        s.querySelector('option[value="narrate"]'),
    )
    expect(narratorSelect).toBeDefined()
    fireEvent.change(narratorSelect!, { target: { value: 'play' } })

    await waitFor(() => expect(onSave).toHaveBeenCalled())
    const [, body] = onSave.mock.calls[0]
    expect(body.voice_config.tts_provider_id).toBe('mistral_voice')
  })
})
```

The exact prop interface for `PersonaVoiceConfig` may include extra optional props beyond `persona`, `onSave`, `playPreview` — if `pnpm tsc --noEmit` complains during Step 3 below, add the missing ones with `undefined` / `vi.fn()` stubs. Do not change the production component to accommodate the test.

- [ ] **Step 2: Run the new test to confirm it fails.**

```bash
cd frontend && pnpm vitest run src/features/voice/components/PersonaVoiceConfig.test.tsx
```

Expected: the test fails because the current `persistVoiceConfig` writes `tts_provider_id: prior?.tts_provider_id ?? null` (line 108) — `prior` is null (the persona has no `voice_config`), so `null` lands in the request body.

- [ ] **Step 3: Modify `persistVoiceConfig` to fall back to `activeTTS.id`.**

In `frontend/src/features/voice/components/PersonaVoiceConfig.tsx`, change line 108 from:

```typescript
            tts_provider_id: prior?.tts_provider_id ?? null,
```

to:

```typescript
            // Persist the implicit default so that the top-bar gate
            // (useVoiceAvailable) and any backend-side reader sees the
            // resolved provider id rather than null. activeTTS already
            // carries the ?? ttsProviders[0] fallback from the closure
            // above.
            tts_provider_id: prior?.tts_provider_id ?? activeTTS?.id ?? null,
```

- [ ] **Step 4: Run the test to confirm it passes.**

```bash
cd frontend && pnpm vitest run src/features/voice/components/PersonaVoiceConfig.test.tsx
```

Expected: pass. If `tsc` complains in the test about missing required props on `PersonaVoiceConfig`, stub them in the test file (do not weaken the production type).

- [ ] **Step 5: Frontend full build.**

```bash
cd frontend && pnpm run build
```

Expected: clean build.

- [ ] **Step 6: Commit.**

```bash
git add \
  frontend/src/features/voice/components/PersonaVoiceConfig.tsx \
  frontend/src/features/voice/components/PersonaVoiceConfig.test.tsx
git commit -m "Persist implicit default tts_provider_id on first persona voice save"
```

---

## Task 4: Backend one-shot migration to backfill `voice_config.tts_provider_id`

**Files:**
- Create: `backend/modules/persona/_migration_tts_provider_id.py`
- Create: `backend/tests/modules/persona/__init__.py` (empty)
- Create: `backend/tests/modules/persona/test_migration_tts_provider_id.py`
- Modify: `backend/main.py` (call `run_if_needed`)

**Goal:** For every persona document where `voice_config.tts_provider_id` is missing or `null` AND the persona has a configured voice (some `integration_configs[<voice_int>].voice_id` set on a known TTS integration), set `voice_config.tts_provider_id` to that integration id. Idempotent. Marker-gated. Runs once on startup before the app accepts traffic.

The migration must not invent `voice_config` from scratch — it should `$set` `voice_config.tts_provider_id` (Mongo dot-notation) and leave any other `voice_config` defaults to deserialise from `VoiceConfigDto`.

**Defining "known TTS integration":** the truth lives in `backend/modules/integrations/_registry.py`. The migration must consult it rather than hardcoding `["xai_voice", "mistral_voice"]`. The pure helper extracted in Step 1 takes the list as a parameter so the test stays decoupled.

- [ ] **Step 1: Write the unit test for the pure helper.**

Create `backend/tests/modules/persona/__init__.py` as an empty file:

```python
```

Create `backend/tests/modules/persona/test_migration_tts_provider_id.py`:

```python
"""Unit tests for the persona tts_provider_id backfill migration helper."""
from backend.modules.persona._migration_tts_provider_id import (
    pick_default_provider_id,
)


TTS_INTEGRATION_IDS = ("xai_voice", "mistral_voice")


def test_returns_none_when_persona_has_no_integration_configs():
    assert pick_default_provider_id({}, TTS_INTEGRATION_IDS) is None


def test_returns_none_when_no_tts_integration_has_a_voice_id():
    persona = {"integration_configs": {"mistral_voice": {}}}
    assert pick_default_provider_id(persona, TTS_INTEGRATION_IDS) is None


def test_returns_the_integration_id_with_a_configured_voice_id():
    persona = {
        "integration_configs": {
            "mistral_voice": {"voice_id": "v-uuid"},
        },
    }
    assert pick_default_provider_id(persona, TTS_INTEGRATION_IDS) == "mistral_voice"


def test_skips_unknown_integrations():
    persona = {
        "integration_configs": {
            "unknown_voice": {"voice_id": "v-uuid"},
        },
    }
    assert pick_default_provider_id(persona, TTS_INTEGRATION_IDS) is None


def test_prefers_the_first_known_integration_in_the_supplied_order():
    # The order of TTS_INTEGRATION_IDS is the deciding tie-break: when
    # multiple TTS integrations on the persona have a voice_id set, we pick
    # whichever appears first in the registry-defined order so the migration
    # is deterministic across re-runs.
    persona = {
        "integration_configs": {
            "mistral_voice": {"voice_id": "m"},
            "xai_voice": {"voice_id": "x"},
        },
    }
    assert pick_default_provider_id(persona, TTS_INTEGRATION_IDS) == "xai_voice"


def test_ignores_falsy_voice_id():
    persona = {
        "integration_configs": {
            "mistral_voice": {"voice_id": ""},
            "xai_voice": {"voice_id": None},
        },
    }
    assert pick_default_provider_id(persona, TTS_INTEGRATION_IDS) is None
```

- [ ] **Step 2: Run the tests to confirm they fail (module does not exist yet).**

```bash
uv run pytest backend/tests/modules/persona/test_migration_tts_provider_id.py -v
```

Expected: collection error / `ModuleNotFoundError` for `backend.modules.persona._migration_tts_provider_id`.

- [ ] **Step 3: Create the migration module.**

Create `backend/modules/persona/_migration_tts_provider_id.py`:

```python
"""One-shot migration: backfill persona.voice_config.tts_provider_id.

Runs once per database on startup, gated by a marker document in the
``_migrations`` collection. Idempotent — re-runs are no-ops.

Background: between alpha and the early beta, the persona-voice editor on
the frontend would only persist ``voice_config.tts_provider_id`` when the
user actively changed the TTS-provider selector. Personas that were
created and only had a voice picked therefore landed in the database with
``integration_configs[<voice_int>].voice_id`` set but no
``voice_config.tts_provider_id``. The cockpit Live-button gate fell back
to "first enabled TTS integration" and looked fine; the top-bar voice-chat
pill did not, and rendered as strikethrough. This migration repairs those
documents so the gates agree.

The frontend persistence path was fixed at the same time (see
``PersonaVoiceConfig.persistVoiceConfig``); this script handles the
existing document corpus.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.modules.integrations._registry import get_all_definitions
from shared.dtos.integrations import IntegrationCapability

_log = logging.getLogger(__name__)
_MARKER_ID = "persona_tts_provider_id_backfill_v1"


def _tts_integration_ids() -> tuple[str, ...]:
    """Snapshot of the registry-known TTS-provider integration ids.

    Order matters for the migration's tie-break behaviour: when a persona
    has voice ids configured on multiple TTS integrations we pick the first
    one in registry order so the result is deterministic. Iteration order
    of the registry is the registration order in
    ``_register_builtin_voice_adapters``, which is stable across runs.
    """
    return tuple(
        defn.id
        for defn in get_all_definitions().values()
        if IntegrationCapability.TTS_PROVIDER in (defn.capabilities or [])
    )


def pick_default_provider_id(
    persona: dict[str, Any], tts_integration_ids: Iterable[str],
) -> str | None:
    """Return the integration id whose ``voice_id`` we should adopt as
    the persona's ``tts_provider_id``, or None if no candidate exists.

    Pure function — easy to unit-test without a database. The order of
    ``tts_integration_ids`` is the tie-break.
    """
    integration_configs = persona.get("integration_configs") or {}
    for integration_id in tts_integration_ids:
        cfg = integration_configs.get(integration_id) or {}
        if cfg.get("voice_id"):
            return integration_id
    return None


async def run_if_needed(db: AsyncIOMotorDatabase, _redis=None) -> None:
    """Run the one-shot backfill unless the marker is already present.

    ``_redis`` is accepted for signature-parity with other migration
    modules but unused — this migration touches Mongo only.
    """
    marker = await db["_migrations"].find_one({"_id": _MARKER_ID})
    if marker is not None:
        return

    _log.warning("persona_tts_provider_id_backfill_v1: running")

    tts_ids = _tts_integration_ids()
    personas = db["personas"]
    updated = 0
    skipped = 0

    # Match documents where tts_provider_id is missing or null. The same
    # filter on a re-run finds nothing because the previous run set the
    # field — that is the idempotency guarantee.
    cursor = personas.find({
        "$or": [
            {"voice_config": {"$exists": False}},
            {"voice_config.tts_provider_id": {"$in": [None, ""]}},
            {"voice_config.tts_provider_id": {"$exists": False}},
        ],
    })
    async for doc in cursor:
        chosen = pick_default_provider_id(doc, tts_ids)
        if chosen is None:
            skipped += 1
            continue
        await personas.update_one(
            {"_id": doc["_id"]},
            {"$set": {"voice_config.tts_provider_id": chosen}},
        )
        updated += 1

    await db["_migrations"].insert_one({
        "_id": _MARKER_ID,
        "applied_at": datetime.now(UTC),
        "updated": updated,
        "skipped": skipped,
    })
    _log.warning(
        "persona_tts_provider_id_backfill_v1: done updated=%d skipped=%d",
        updated, skipped,
    )
```

If `IntegrationCapability.TTS_PROVIDER` does not exist under that exact name, grep for the actual enum value (`rg -n "TTS_PROVIDER\\|tts_provider" shared/dtos/integrations.py backend/modules/integrations`) and use the canonical reference. Do not invent the symbol.

- [ ] **Step 4: Run the unit tests to confirm they pass.**

```bash
uv run pytest backend/tests/modules/persona/test_migration_tts_provider_id.py -v
```

Expected: all six tests pass.

- [ ] **Step 5: Wire the migration into startup.**

In `backend/main.py`, near the existing migration imports (around lines 77-83):

Add the import block:

```python
from backend.modules.persona._migration_tts_provider_id import (
    run_if_needed as run_persona_tts_provider_id_backfill,
)
```

In the `lifespan` async context manager, **after** `await persona_init_indexes(db)` (current line 101), call the migration:

```python
    await persona_init_indexes(db)
    # Backfill voice_config.tts_provider_id for personas created before the
    # frontend started persisting the implicit default. Marker-gated, runs
    # once. See backend/modules/persona/_migration_tts_provider_id.py.
    await run_persona_tts_provider_id_backfill(db)
```

The migration runs after the persona indexes are in place but before the app starts serving traffic — the same shape as `run_providers_migration` (current line 116).

- [ ] **Step 6: Verify the backend file syntax-compiles.**

```bash
uv run python -m py_compile backend/main.py backend/modules/persona/_migration_tts_provider_id.py
```

Expected: silent (clean compile).

- [ ] **Step 7: Run the persona migration tests once more to confirm nothing regressed by the import wiring.**

```bash
uv run pytest backend/tests/modules/persona/ -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit.**

```bash
git add \
  backend/modules/persona/_migration_tts_provider_id.py \
  backend/tests/modules/persona/__init__.py \
  backend/tests/modules/persona/test_migration_tts_provider_id.py \
  backend/main.py
git commit -m "Backfill persona.voice_config.tts_provider_id on startup"
```

---

## Task 5: End-to-end manual verification

Automated tests cover the wiring; this task confirms the bug is gone in the real app and that no other persona has been broken by the migration.

- [ ] **Step 1: Snapshot the current state of `personas` for affected user before the migration runs.**

```bash
docker compose exec -T mongodb mongosh --quiet --eval '
  db = db.getSiblingDB("chatsune");
  print("--- BEFORE: personas missing tts_provider_id ---");
  db.personas.find(
    { $or: [
        { voice_config: { $exists: false } },
        { "voice_config.tts_provider_id": { $in: [null, ""] } },
        { "voice_config.tts_provider_id": { $exists: false } },
    ]},
    { name: 1, "voice_config.tts_provider_id": 1, "integration_configs": 1 },
  ).forEach(p => printjson(p));
'
```

Record the list of personas — at minimum, `test2` should appear. Save the output to scratch.

- [ ] **Step 2: Restart the backend so the migration runs.**

If the backend runs in Docker:

```bash
docker compose restart backend
docker compose logs --tail=80 backend | grep -i "persona_tts_provider_id"
```

Expected: a log line `persona_tts_provider_id_backfill_v1: running` followed by `persona_tts_provider_id_backfill_v1: done updated=N skipped=M`. If you run the backend with `uv run` outside Docker, restart that process and check its stderr instead.

- [ ] **Step 3: Verify the migration touched the personas you expected.**

```bash
docker compose exec -T mongodb mongosh --quiet --eval '
  db = db.getSiblingDB("chatsune");
  print("--- AFTER: personas missing tts_provider_id (should be empty unless they have no voice configured) ---");
  db.personas.find(
    { $or: [
        { voice_config: { $exists: false } },
        { "voice_config.tts_provider_id": { $in: [null, ""] } },
        { "voice_config.tts_provider_id": { $exists: false } },
    ]},
    { name: 1, "voice_config.tts_provider_id": 1, "integration_configs": 1 },
  ).forEach(p => printjson(p));
  print("\n--- migration marker ---");
  db._migrations.find({ _id: "persona_tts_provider_id_backfill_v1" }).forEach(printjson);
'
```

Expected: any persona that previously had a configured voice now has `voice_config.tts_provider_id` set; personas with no voice configured at all may remain untouched (that is the correct behaviour — the migration backfills only where a voice exists).

- [ ] **Step 4: Verify the marker prevents re-runs.**

Restart the backend a second time:

```bash
docker compose restart backend
docker compose logs --tail=80 backend | grep -i "persona_tts_provider_id"
```

Expected: **no** `running` log line on the second restart (the marker is present, so `run_if_needed` returns early).

- [ ] **Step 5: Verify the bug is gone in the browser.**

1. Hard-reload the frontend (`Ctrl+F5`) and open a chat with persona `test2` (the one currently showing strikethrough).
2. Confirm the top-bar "VOICE CHAT" pill is **not** struck through and reads "Voice chat" with the gold-amber tint of the available state.
3. Click into Live mode via the cockpit Live button to confirm voice chat actually works (smoke test — no functional regression).
4. Open the persona voice editor (gear / overlay / persona settings) and confirm the TTS-provider `<select>` shows "Mistral" without the "(default)" suffix (i.e. it now reflects the persisted choice).

- [ ] **Step 6: Verify Task 3 prevents new regressions.**

1. In the User-Modal, create a fresh persona `test3`. Pick any TTS integration's voice without ever touching the TTS-provider selector.
2. Open the chat for `test3`. Confirm the top-bar pill is **not** struck through immediately (no migration ran for `test3`; the new on-save behaviour set `tts_provider_id`).
3. Inspect the database to confirm:

```bash
docker compose exec -T mongodb mongosh --quiet --eval '
  db = db.getSiblingDB("chatsune");
  db.personas.find({name: "test3"}, {"voice_config.tts_provider_id": 1, "integration_configs": 1}).forEach(printjson);
'
```

Expected: `voice_config.tts_provider_id` matches the picked integration id.

- [ ] **Step 7: Final commit (only if any docs / changelog updates were needed).**

If steps 1-6 pass without further code changes, no commit is needed for Task 5.

---

## Out of Scope (Explicitly)

- **Larger refactor of the voice-resolver pattern.** Tasks 1-2 export an existing function but do not unify the cockpit/top-bar gate into a single helper. Doing so would touch `ChatView`, `LiveButton`, and `ConversationModeButton` together and is a separate change.
- **`voice_config` defaults at persona creation.** Backend-side, the `CreatePersonaDto.voice_config` is still `None` by default. We are not changing the create endpoint — Task 3 catches the case at first save, Task 4 cleans up the historical artefacts. Tightening the create endpoint is a follow-up if persona-create-without-voice flows turn out to also write null persistently.
- **STT provider id alignment.** STT lives in `useVoiceSettingsStore.stt_provider_id` (user-level, not persona-level) and follows a different lifecycle. Out of scope here — see the existing comment in `useVoiceAvailable` for the rationale.
- **Tests against a live MongoDB.** Per `MEMORY.md → feedback_db_tests_on_host`, tests that hit MongoDB are excluded from the host-side run. Task 4's automated test is a pure-function unit test deliberately. Migration end-to-end safety is verified manually via Task 5.

---

## Subagent Constraints (REQUIRED — do not violate)

For every subagent dispatched to execute this plan:

- Stay on the current branch. **Do not merge, do not push, do not switch or create branches** (per `MEMORY.md → feedback_subagent_no_merge`).
- Do not skip pre-commit hooks (`--no-verify`) or bypass GPG signing.
- Do not invent `IntegrationCapability` symbol names — grep for the canonical reference.
- Do not weaken any production type signature to make a test compile; stub the test instead.
- If a step's expected output diverges from reality, stop and report rather than improvising a fix.
