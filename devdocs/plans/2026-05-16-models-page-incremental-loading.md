# Models page incremental loading — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the all-or-nothing "Loading models…" screen on the Models tab with per-provider incremental rendering and inline error visibility.

**Architecture:** Refactor `useEnrichedModels` into two phases — Phase A lists every connection and commits a skeleton; Phase B fires per-connection model fetches that each write through to state independently. The `ModelBrowser` renders the skeleton straight away and gets per-group `status` (`loading` / `ready` / `error`) for in-group indicators. Generation counter guards against stale writes. External `loading` field keeps today's "fully settled" semantics so other consumers (`EditTab`, `OverviewTab`, `UserModal`) don't regress.

**Tech Stack:** React 18, TypeScript, Vitest, `@testing-library/react` (`renderHook`, `act`, `waitFor`), Tailwind for styling.

**Reference:** `devdocs/specs/2026-05-16-models-page-incremental-loading-design.md`

---

## File map

- **Modify** `frontend/src/core/hooks/useEnrichedModels.ts` — extend `ConnectionModelGroup` with `status`/`error`, split `refresh()` into phases A and B, add generation counter, preserve external `loading` semantics.
- **Create** `frontend/src/core/hooks/__tests__/useEnrichedModels.test.tsx` — new test file with mocked APIs to exercise the phased flow, per-group writes, error capture, settle gating, and stale-write protection.
- **Modify** `frontend/src/app/components/model-browser/ModelBrowser.tsx` — drop the top-level loading branch; gate phase-A placeholder on `groups.length`; relax `filteredGroups` to keep loading/error groups; hide filter bar during phase A; pass `status`/`error` into `ConnectionGroup`.
- **Modify** `frontend/src/app/components/model-browser/__tests__/ModelBrowser.test.tsx` — extend `hubState` with `status`/`error`; add tests for phase-A placeholder, per-group loading spinner, per-group error message, and filter-bar hiding.

No backend, no `shared/`, no event-bus, no other consumers touched.

---

## Conventions for every task

- Run frontend commands from the `frontend/` directory.
- Test runner: `pnpm vitest run <path>` for one file; `pnpm test --run` for everything.
- Type check: `pnpm tsc --noEmit`.
- Commit message style: imperative, free-form (per `~/.claude/CLAUDE.md`).
- After each commit, the next task starts from a clean tree.

---

### Task 1: Extend `ConnectionModelGroup` with `status` and `error` (no behaviour change)

**Files:**
- Modify: `frontend/src/core/hooks/useEnrichedModels.ts:17-20` (interface) and `:135-164` (build groups)
- Create: `frontend/src/core/hooks/__tests__/useEnrichedModels.test.tsx`

- [ ] **Step 1: Create the test file with mocks and a baseline test.**

Create `frontend/src/core/hooks/__tests__/useEnrichedModels.test.tsx`:

```tsx
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type {
  Connection,
  ModelMetaDto,
  UserModelConfigDto,
} from '../../types/llm'
import type {
  PremiumProviderAccount,
  PremiumProviderDefinition,
} from '../../types/providers'

vi.mock('../../api/llm', () => ({
  llmApi: {
    listConnections: vi.fn(),
    listUserModelConfigs: vi.fn(),
    listConnectionModels: vi.fn(),
  },
}))

vi.mock('../../api/providers', () => ({
  providersApi: {
    catalogue: vi.fn(),
    listAccounts: vi.fn(),
    listProviderModels: vi.fn(),
  },
}))

vi.mock('../../websocket/eventBus', () => ({
  eventBus: { on: vi.fn(() => () => {}) },
}))

import { llmApi } from '../../api/llm'
import { providersApi } from '../../api/providers'
import { useEnrichedModels } from '../useEnrichedModels'

function makeConn(id: string, slug: string, createdAt: string): Connection {
  return {
    id,
    user_id: 'u',
    adapter_type: 'ollama_http',
    display_name: slug,
    slug,
    config: {},
    last_test_status: 'valid',
    last_test_error: null,
    last_test_at: null,
    created_at: createdAt,
    updated_at: createdAt,
    is_system_managed: false,
  }
}

function makeModel(uid: string, name: string): ModelMetaDto {
  return {
    connection_id: uid.split(':')[0],
    connection_slug: uid.split(':')[0],
    connection_display_name: uid.split(':')[0],
    model_id: uid.split(':').slice(1).join(':'),
    display_name: name,
    context_window: 8000,
    supports_reasoning: false,
    supports_vision: false,
    supports_tool_calls: false,
    reasoning: { kind: 'none', effort: null, default_on: false },
    tools: { supported: false, exclusive_with_reasoning: false },
    first_class_support: false,
    parameter_count: null,
    raw_parameter_count: null,
    quantisation_level: null,
    unique_id: uid,
  } as ModelMetaDto
}

beforeEach(() => {
  vi.clearAllMocks()
  ;(llmApi.listConnections as ReturnType<typeof vi.fn>).mockResolvedValue([])
  ;(llmApi.listUserModelConfigs as ReturnType<typeof vi.fn>).mockResolvedValue([] as UserModelConfigDto[])
  ;(llmApi.listConnectionModels as ReturnType<typeof vi.fn>).mockResolvedValue([])
  ;(providersApi.catalogue as ReturnType<typeof vi.fn>).mockResolvedValue([] as PremiumProviderDefinition[])
  ;(providersApi.listAccounts as ReturnType<typeof vi.fn>).mockResolvedValue([] as PremiumProviderAccount[])
  ;(providersApi.listProviderModels as ReturnType<typeof vi.fn>).mockResolvedValue([])
})

describe('useEnrichedModels — baseline', () => {
  it('returns ready groups with models for each connection', async () => {
    ;(llmApi.listConnections as ReturnType<typeof vi.fn>).mockResolvedValue([
      makeConn('c1', 'one', '2026-05-01T00:00:00Z'),
    ])
    ;(llmApi.listConnectionModels as ReturnType<typeof vi.fn>).mockResolvedValue([
      makeModel('c1:m1', 'Model M1'),
    ])

    const { result } = renderHook(() => useEnrichedModels())

    await waitFor(() => expect(result.current.loading).toBe(false))

    expect(result.current.groups).toHaveLength(1)
    expect(result.current.groups[0].connection.id).toBe('c1')
    expect(result.current.groups[0].status).toBe('ready')
    expect(result.current.groups[0].models).toHaveLength(1)
    expect(result.current.groups[0].models[0].display_name).toBe('Model M1')
  })
})
```

- [ ] **Step 2: Run the test — it should fail because `status` is not on the interface yet.**

Run: `cd frontend && pnpm vitest run src/core/hooks/__tests__/useEnrichedModels.test.tsx`
Expected: FAIL with TypeScript error or assertion failure on `status`.

- [ ] **Step 3: Add `status` and `error` to the interface.**

Modify `frontend/src/core/hooks/useEnrichedModels.ts`, lines 17-20:

```ts
export interface ConnectionModelGroup {
  connection: Connection
  models: EnrichedModelDto[]
  status: 'loading' | 'ready' | 'error'
  error?: string
}
```

- [ ] **Step 4: Set every group to `status: 'ready'` in the current implementation so the baseline behaviour is unchanged.**

In `useEnrichedModels.ts`, locate the two group-building blocks. For premium groups (currently lines 135-147), change the object literal to include `status: 'ready'`:

```ts
const premiumGroups: ConnectionModelGroup[] = premiumConns.map(
  (connection, idx) => ({
    connection,
    status: 'ready' as const,
    models: premiumModels[idx]
      .map<EnrichedModelDto>((m) => {
        const cfg = configByUid.get(m.unique_id) ?? null
        const supports_reasoning =
          cfg?.custom_supports_reasoning ?? m.supports_reasoning
        return { ...m, supports_reasoning, user_config: cfg }
      })
      .sort((a, b) => a.display_name.localeCompare(b.display_name)),
  }),
)
```

Do the same for `userGroups` (currently lines 149-164): add `status: 'ready' as const` to the object literal.

- [ ] **Step 5: Run the test — it should pass.**

Run: `cd frontend && pnpm vitest run src/core/hooks/__tests__/useEnrichedModels.test.tsx`
Expected: PASS.

- [ ] **Step 6: Type-check the whole frontend (the `ConnectionGroup` JSX in `ModelBrowser.tsx` does not touch `status` yet, so this should pass).**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: PASS.

- [ ] **Step 7: Update `ModelBrowser.test.tsx` `hubState` shape so its mocked groups satisfy the new interface.**

In `frontend/src/app/components/model-browser/__tests__/ModelBrowser.test.tsx`, change the `hubState` type (around line 34-42) and the two test cases that populate `hubState.groups` to include `status: 'ready' as const` on each group object. Example for one test (line 119-127):

```ts
hubState.groups = [
  {
    connection: makeConnection(),
    status: 'ready',
    models: [
      makeModel('conn:m1', 'Model One', true),
      makeModel('conn:m2', 'Model Two', false),
    ],
  },
]
```

Update the `hubState` declaration:

```ts
const hubState: {
  groups: Array<{
    connection: Connection
    status: 'loading' | 'ready' | 'error'
    error?: string
    models: EnrichedModelDto[]
  }>
  loading: boolean
  error: string | null
} = {
  groups: [],
  loading: false,
  error: null,
}
```

- [ ] **Step 8: Run the ModelBrowser tests — they should still pass.**

Run: `cd frontend && pnpm vitest run src/app/components/model-browser/__tests__/ModelBrowser.test.tsx`
Expected: PASS.

- [ ] **Step 9: Commit.**

```bash
git add frontend/src/core/hooks/useEnrichedModels.ts \
        frontend/src/core/hooks/__tests__/useEnrichedModels.test.tsx \
        frontend/src/app/components/model-browser/__tests__/ModelBrowser.test.tsx
git commit -m "Add status field to ConnectionModelGroup"
```

---

### Task 2: Phase A — commit a group skeleton before any model fetch completes

**Files:**
- Modify: `frontend/src/core/hooks/useEnrichedModels.ts:81-172` (the `refresh` callback)
- Modify: `frontend/src/core/hooks/__tests__/useEnrichedModels.test.tsx` (add test)

- [ ] **Step 1: Add a deferred-promise helper at the top of the test file (after the imports, before `beforeEach`).**

```ts
function deferred<T>() {
  let resolve!: (v: T) => void
  let reject!: (e: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}
```

- [ ] **Step 2: Write a failing test that asserts the skeleton appears before per-group fetches resolve.**

Append to `useEnrichedModels.test.tsx`:

```ts
describe('useEnrichedModels — phase A', () => {
  it('commits group skeleton before any model fetch resolves', async () => {
    ;(llmApi.listConnections as ReturnType<typeof vi.fn>).mockResolvedValue([
      makeConn('c1', 'one', '2026-05-01T00:00:00Z'),
      makeConn('c2', 'two', '2026-05-02T00:00:00Z'),
    ])

    const heldOne = deferred<ModelMetaDto[]>()
    const heldTwo = deferred<ModelMetaDto[]>()
    ;(llmApi.listConnectionModels as ReturnType<typeof vi.fn>).mockImplementation(
      (id: string) => (id === 'c1' ? heldOne.promise : heldTwo.promise),
    )

    const { result } = renderHook(() => useEnrichedModels())

    await waitFor(() => expect(result.current.groups).toHaveLength(2))

    expect(result.current.groups[0].connection.id).toBe('c1')
    expect(result.current.groups[0].status).toBe('loading')
    expect(result.current.groups[0].models).toHaveLength(0)
    expect(result.current.groups[1].status).toBe('loading')

    // Clean up so the hook does not log unhandled rejections after the test.
    await act(async () => {
      heldOne.resolve([])
      heldTwo.resolve([])
    })
  })
})
```

- [ ] **Step 3: Run the test — it should fail because today's hook waits for all model fetches before committing groups.**

Run: `cd frontend && pnpm vitest run src/core/hooks/__tests__/useEnrichedModels.test.tsx -t "phase A"`
Expected: FAIL — `waitFor` times out because groups stays empty until model fetches resolve.

- [ ] **Step 4: Refactor `refresh` to commit phase A separately.**

Replace the body of `refresh` in `useEnrichedModels.ts` (lines 81-172) with a phased implementation. The shape:

```ts
const refresh = useCallback(async () => {
  setError(null)
  setLoading(true)
  try {
    // Phase A: list providers
    const [connections, userConfigs, catalogue, accounts] = await Promise.all([
      llmApi.listConnections(),
      llmApi.listUserModelConfigs(),
      providersApi.catalogue().catch(() => [] as PremiumProviderDefinition[]),
      providersApi.listAccounts().catch(() => [] as PremiumProviderAccount[]),
    ])

    const configByUid = new Map<string, UserModelConfigDto>()
    for (const cfg of userConfigs) configByUid.set(cfg.model_unique_id, cfg)

    const sortedConns = [...connections].sort(
      (a, b) => a.created_at.localeCompare(b.created_at),
    )

    const cataloguebyId = new Map(catalogue.map((d) => [d.id, d]))
    const premiumConns: Connection[] = []
    for (const acct of accounts) {
      const defn = cataloguebyId.get(acct.provider_id)
      if (!defn) continue
      premiumConns.push(toPseudoConnection(defn, acct))
    }

    const skeleton: ConnectionModelGroup[] = [
      ...premiumConns.map<ConnectionModelGroup>((c) => ({
        connection: c, status: 'loading', models: [],
      })),
      ...sortedConns.map<ConnectionModelGroup>((c) => ({
        connection: c, status: 'loading', models: [],
      })),
    ]
    setGroups(skeleton)

    // Phase B: per-group fetches (filled in next tasks)
    const fetchOne = (c: Connection): Promise<ModelMetaDto[]> =>
      c.id.startsWith('premium:')
        ? providersApi.listProviderModels(c.slug)
        : llmApi.listConnectionModels(c.id)

    // Fire all in parallel; do not await — each will update its own group.
    for (const c of [...premiumConns, ...sortedConns]) {
      void fetchOne(c)
        .then((models) => {
          // Placeholder — wired up in Task 3.
        })
        .catch(() => {
          // Placeholder — wired up in Task 4.
        })
    }
  } catch (err) {
    setError(err instanceof Error ? err.message : 'Could not load models.')
  } finally {
    setLoading(false)
  }
}, [])
```

Note: `loading` flipping to `false` here is **temporary** — Task 5 will make it stay `true` until all groups settle.

- [ ] **Step 5: Run the new test — it should now pass.**

Run: `cd frontend && pnpm vitest run src/core/hooks/__tests__/useEnrichedModels.test.tsx -t "phase A"`
Expected: PASS.

- [ ] **Step 6: Run the baseline test — it will now fail because Phase B is not wired yet (groups stay in `loading`).**

Run: `cd frontend && pnpm vitest run src/core/hooks/__tests__/useEnrichedModels.test.tsx -t "baseline"`
Expected: FAIL — `status` is `'loading'`, not `'ready'`.

This failure is expected; Task 3 will fix it. Do NOT commit until Task 3 is done.

- [ ] **Step 7: (No commit yet — continue to Task 3.)**

---

### Task 3: Phase B — per-group ready writes

**Files:**
- Modify: `frontend/src/core/hooks/useEnrichedModels.ts` (the `.then` placeholder from Task 2)
- Modify: `frontend/src/core/hooks/__tests__/useEnrichedModels.test.tsx` (add test)

- [ ] **Step 1: Write a failing test that asserts a fast provider's models appear while a slow provider stays in loading.**

Append to `useEnrichedModels.test.tsx`:

```ts
describe('useEnrichedModels — phase B ready', () => {
  it('writes ready status and models for one group while another is still loading', async () => {
    ;(llmApi.listConnections as ReturnType<typeof vi.fn>).mockResolvedValue([
      makeConn('c1', 'one', '2026-05-01T00:00:00Z'),
      makeConn('c2', 'two', '2026-05-02T00:00:00Z'),
    ])

    const slow = deferred<ModelMetaDto[]>()
    ;(llmApi.listConnectionModels as ReturnType<typeof vi.fn>).mockImplementation(
      async (id: string) => (id === 'c1' ? [makeModel('c1:m1', 'Fast')] : slow.promise),
    )

    const { result } = renderHook(() => useEnrichedModels())

    await waitFor(() =>
      expect(result.current.groups.find((g) => g.connection.id === 'c1')?.status)
        .toBe('ready'),
    )

    const fast = result.current.groups.find((g) => g.connection.id === 'c1')!
    expect(fast.models).toHaveLength(1)
    expect(fast.models[0].display_name).toBe('Fast')

    const slowGroup = result.current.groups.find((g) => g.connection.id === 'c2')!
    expect(slowGroup.status).toBe('loading')
    expect(slowGroup.models).toHaveLength(0)

    await act(async () => { slow.resolve([]) })
  })
})
```

- [ ] **Step 2: Run the test — it should fail (group never reaches `'ready'`).**

Run: `cd frontend && pnpm vitest run src/core/hooks/__tests__/useEnrichedModels.test.tsx -t "phase B ready"`
Expected: FAIL.

- [ ] **Step 3: Wire the `.then` branch in `refresh` to update only the matching group.**

In the for-loop from Task 2 step 4, replace the `.then` placeholder body. The function needs to enrich models and write per-group state.

Extract the enrichment into a helper local to `refresh` (so it can access `configByUid`):

```ts
const enrichModels = (models: ModelMetaDto[]): EnrichedModelDto[] =>
  models
    .map<EnrichedModelDto>((m) => {
      const cfg = configByUid.get(m.unique_id) ?? null
      const supports_reasoning =
        cfg?.custom_supports_reasoning ?? m.supports_reasoning
      return { ...m, supports_reasoning, user_config: cfg }
    })
    .sort((a, b) => a.display_name.localeCompare(b.display_name))
```

And update the for-loop:

```ts
for (const c of [...premiumConns, ...sortedConns]) {
  void fetchOne(c)
    .then((models) => {
      setGroups((prev) =>
        prev.map((g) =>
          g.connection.id === c.id
            ? { ...g, status: 'ready', models: enrichModels(models), error: undefined }
            : g,
        ),
      )
    })
    .catch(() => {
      // Placeholder — wired up in Task 4.
    })
}
```

- [ ] **Step 4: Run the phase-B ready test — it should pass.**

Run: `cd frontend && pnpm vitest run src/core/hooks/__tests__/useEnrichedModels.test.tsx -t "phase B ready"`
Expected: PASS.

- [ ] **Step 5: Run the baseline test — it should now pass again.**

Run: `cd frontend && pnpm vitest run src/core/hooks/__tests__/useEnrichedModels.test.tsx -t "baseline"`
Expected: PASS.

- [ ] **Step 6: Run all hook tests to make sure nothing else regressed.**

Run: `cd frontend && pnpm vitest run src/core/hooks/__tests__/useEnrichedModels.test.tsx`
Expected: PASS.

- [ ] **Step 7: Commit.**

```bash
git add frontend/src/core/hooks/useEnrichedModels.ts \
        frontend/src/core/hooks/__tests__/useEnrichedModels.test.tsx
git commit -m "Split useEnrichedModels into phase A skeleton and per-group ready writes"
```

---

### Task 4: Phase B — per-group error capture

**Files:**
- Modify: `frontend/src/core/hooks/useEnrichedModels.ts` (the `.catch` placeholder)
- Modify: `frontend/src/core/hooks/__tests__/useEnrichedModels.test.tsx` (add test)

- [ ] **Step 1: Write a failing test that asserts a rejecting fetch lands the group in `'error'` status with the message, while siblings stay unaffected.**

Append:

```ts
describe('useEnrichedModels — phase B error', () => {
  it('marks a single group as error without affecting siblings', async () => {
    ;(llmApi.listConnections as ReturnType<typeof vi.fn>).mockResolvedValue([
      makeConn('c1', 'one', '2026-05-01T00:00:00Z'),
      makeConn('c2', 'two', '2026-05-02T00:00:00Z'),
    ])
    ;(llmApi.listConnectionModels as ReturnType<typeof vi.fn>).mockImplementation(
      async (id: string) => {
        if (id === 'c1') return [makeModel('c1:m1', 'Ok')]
        throw new Error('upstream 503')
      },
    )

    const { result } = renderHook(() => useEnrichedModels())

    await waitFor(() =>
      expect(result.current.groups.find((g) => g.connection.id === 'c2')?.status)
        .toBe('error'),
    )

    const bad = result.current.groups.find((g) => g.connection.id === 'c2')!
    expect(bad.error).toContain('upstream 503')
    expect(bad.models).toHaveLength(0)

    const ok = result.current.groups.find((g) => g.connection.id === 'c1')!
    expect(ok.status).toBe('ready')
    expect(ok.models).toHaveLength(1)
  })
})
```

- [ ] **Step 2: Run the test — it should fail (group stays `'loading'`).**

Run: `cd frontend && pnpm vitest run src/core/hooks/__tests__/useEnrichedModels.test.tsx -t "phase B error"`
Expected: FAIL.

- [ ] **Step 3: Replace the `.catch` placeholder.**

```ts
.catch((err) => {
  const message = err instanceof Error ? err.message : 'Could not load models.'
  setGroups((prev) =>
    prev.map((g) =>
      g.connection.id === c.id
        ? { ...g, status: 'error', error: message }
        : g,
    ),
  )
})
```

- [ ] **Step 4: Run the test — it should pass.**

Run: `cd frontend && pnpm vitest run src/core/hooks/__tests__/useEnrichedModels.test.tsx -t "phase B error"`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add frontend/src/core/hooks/useEnrichedModels.ts \
        frontend/src/core/hooks/__tests__/useEnrichedModels.test.tsx
git commit -m "Capture per-group fetch errors in useEnrichedModels"
```

---

### Task 5: External `loading` stays true until all groups settle

**Files:**
- Modify: `frontend/src/core/hooks/useEnrichedModels.ts` (settle tracking, `loading` flip)
- Modify: `frontend/src/core/hooks/__tests__/useEnrichedModels.test.tsx` (add test)

- [ ] **Step 1: Write a failing test that asserts `loading` is still `true` after phase A but before all per-group fetches settle, then flips to `false` once they do.**

Append:

```ts
describe('useEnrichedModels — loading settle gate', () => {
  it('keeps loading true while any group is still fetching, flips false once all settled', async () => {
    ;(llmApi.listConnections as ReturnType<typeof vi.fn>).mockResolvedValue([
      makeConn('c1', 'one', '2026-05-01T00:00:00Z'),
    ])
    const held = deferred<ModelMetaDto[]>()
    ;(llmApi.listConnectionModels as ReturnType<typeof vi.fn>).mockReturnValue(held.promise)

    const { result } = renderHook(() => useEnrichedModels())

    await waitFor(() => expect(result.current.groups).toHaveLength(1))
    // Group skeleton committed but model fetch still in flight.
    expect(result.current.loading).toBe(true)

    await act(async () => {
      held.resolve([makeModel('c1:m1', 'Done')])
    })

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.groups[0].status).toBe('ready')
  })
})
```

- [ ] **Step 2: Run the test — it should fail because Task 2 currently flips `loading` to false right after phase A.**

Run: `cd frontend && pnpm vitest run src/core/hooks/__tests__/useEnrichedModels.test.tsx -t "loading settle gate"`
Expected: FAIL.

- [ ] **Step 3: Move the `setLoading(false)` out of the `finally` block and into a settle counter that flips when the last group has resolved or errored.**

In `useEnrichedModels.ts`, remove `setLoading(false)` from the `finally` block (keep `setError(null); setLoading(true)` at the top of `refresh`). Inside `refresh`, after the skeleton commit and before the for-loop, set up a counter:

```ts
const total = premiumConns.length + sortedConns.length
if (total === 0) {
  setLoading(false)
  return
}
let settled = 0
const markSettled = () => {
  settled += 1
  if (settled >= total) setLoading(false)
}
```

Then in both the `.then` and `.catch` arms of the for-loop, call `markSettled()` after the `setGroups` call:

```ts
for (const c of [...premiumConns, ...sortedConns]) {
  void fetchOne(c)
    .then((models) => {
      setGroups((prev) =>
        prev.map((g) =>
          g.connection.id === c.id
            ? { ...g, status: 'ready', models: enrichModels(models), error: undefined }
            : g,
        ),
      )
      markSettled()
    })
    .catch((err) => {
      const message = err instanceof Error ? err.message : 'Could not load models.'
      setGroups((prev) =>
        prev.map((g) =>
          g.connection.id === c.id
            ? { ...g, status: 'error', error: message }
            : g,
        ),
      )
      markSettled()
    })
}
```

Also make sure if phase A itself throws, `setLoading(false)` still runs — re-add it to the outer `catch`:

```ts
} catch (err) {
  setError(err instanceof Error ? err.message : 'Could not load models.')
  setLoading(false)
}
// no finally
```

- [ ] **Step 4: Run the new test — it should pass.**

Run: `cd frontend && pnpm vitest run src/core/hooks/__tests__/useEnrichedModels.test.tsx -t "loading settle gate"`
Expected: PASS.

- [ ] **Step 5: Run all hook tests.**

Run: `cd frontend && pnpm vitest run src/core/hooks/__tests__/useEnrichedModels.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit.**

```bash
git add frontend/src/core/hooks/useEnrichedModels.ts \
        frontend/src/core/hooks/__tests__/useEnrichedModels.test.tsx
git commit -m "Gate useEnrichedModels.loading on all groups settling"
```

---

### Task 6: Generation counter guards against stale per-group writes

**Files:**
- Modify: `frontend/src/core/hooks/useEnrichedModels.ts`
- Modify: `frontend/src/core/hooks/__tests__/useEnrichedModels.test.tsx`

- [ ] **Step 1: Write a failing test that triggers a refresh while a previous fetch is still in flight, and asserts the stale resolution does not overwrite the new state.**

Append:

```ts
describe('useEnrichedModels — stale write guard', () => {
  it('drops a per-group write from a superseded refresh', async () => {
    ;(llmApi.listConnections as ReturnType<typeof vi.fn>).mockResolvedValue([
      makeConn('c1', 'one', '2026-05-01T00:00:00Z'),
    ])

    const firstHeld = deferred<ModelMetaDto[]>()
    const secondModels = [makeModel('c1:fresh', 'Fresh')]
    const calls: Array<{ id: string }> = []
    ;(llmApi.listConnectionModels as ReturnType<typeof vi.fn>).mockImplementation(
      async (id: string) => {
        calls.push({ id })
        return calls.length === 1 ? firstHeld.promise : secondModels
      },
    )

    const { result } = renderHook(() => useEnrichedModels())
    await waitFor(() => expect(result.current.groups).toHaveLength(1))

    // Trigger a second refresh that will resolve before the first.
    await act(async () => { await result.current.refresh() })
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.groups[0].models[0].display_name).toBe('Fresh')

    // Now let the first refresh's held fetch resolve with stale data.
    await act(async () => {
      firstHeld.resolve([makeModel('c1:stale', 'Stale')])
    })

    // State must still reflect the second refresh, not the late stale write.
    expect(result.current.groups[0].models[0].display_name).toBe('Fresh')
    expect(result.current.groups[0].status).toBe('ready')
  })
})
```

- [ ] **Step 2: Run the test — it should fail (stale write currently overwrites the fresh state).**

Run: `cd frontend && pnpm vitest run src/core/hooks/__tests__/useEnrichedModels.test.tsx -t "stale write guard"`
Expected: FAIL.

- [ ] **Step 3: Add a generation counter via `useRef`.**

At the top of `useEnrichedModels`, alongside the existing `useState` calls, add:

```ts
const generationRef = useRef(0)
```

Add `useRef` to the React import at line 1 if it is not already there.

Inside `refresh`, at the very top after `setError(null); setLoading(true);`, capture the new generation:

```ts
const myGeneration = ++generationRef.current
```

Then guard every state-writing branch (the phase-A skeleton commit, both per-group `setGroups` calls, the `markSettled` `setLoading`, and the outer catch's `setError`/`setLoading`) with:

```ts
if (generationRef.current !== myGeneration) return
```

The cleanest pattern is a helper inside `refresh`:

```ts
const isLive = () => generationRef.current === myGeneration
```

…and wrap every state write:

```ts
if (isLive()) setGroups(skeleton)
// …
.then((models) => {
  if (!isLive()) return
  setGroups((prev) => prev.map(...))
  markSettled()
})
.catch((err) => {
  if (!isLive()) return
  setGroups((prev) => prev.map(...))
  markSettled()
})
```

And in `markSettled`:

```ts
const markSettled = () => {
  settled += 1
  if (settled >= total && isLive()) setLoading(false)
}
```

And in the outer catch:

```ts
} catch (err) {
  if (!isLive()) return
  setError(err instanceof Error ? err.message : 'Could not load models.')
  setLoading(false)
}
```

- [ ] **Step 4: Run the test — it should pass.**

Run: `cd frontend && pnpm vitest run src/core/hooks/__tests__/useEnrichedModels.test.tsx -t "stale write guard"`
Expected: PASS.

- [ ] **Step 5: Run all hook tests.**

Run: `cd frontend && pnpm vitest run src/core/hooks/__tests__/useEnrichedModels.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit.**

```bash
git add frontend/src/core/hooks/useEnrichedModels.ts \
        frontend/src/core/hooks/__tests__/useEnrichedModels.test.tsx
git commit -m "Guard useEnrichedModels writes with a generation counter"
```

---

### Task 7: ModelBrowser — render phase-A placeholder via `groups.length`

**Files:**
- Modify: `frontend/src/app/components/model-browser/ModelBrowser.tsx:79-104`
- Modify: `frontend/src/app/components/model-browser/__tests__/ModelBrowser.test.tsx`

- [ ] **Step 1: Write a failing test that asserts the new phase-A placeholder is shown when `groups` is empty and `loading` is true.**

Add a new `describe` block at the end of `ModelBrowser.test.tsx`:

```ts
describe('ModelBrowser — phase A placeholder', () => {
  it('shows a spinner placeholder while groups are still being listed', async () => {
    hubState.groups = []
    hubState.loading = true
    hubState.error = null

    const { ModelBrowser } = await import('../ModelBrowser')
    render(<ModelBrowser />)

    expect(screen.getByTestId('model-browser-phase-a')).toBeInTheDocument()
  })

  it('shows the empty-connections hint only when not loading and no groups', async () => {
    hubState.groups = []
    hubState.loading = false
    hubState.error = null

    const { ModelBrowser } = await import('../ModelBrowser')
    render(<ModelBrowser />)

    expect(screen.queryByTestId('model-browser-phase-a')).toBeNull()
    expect(screen.getByText(/No LLM connection configured/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run the tests — first should fail (no element with that test id).**

Run: `cd frontend && pnpm vitest run src/app/components/model-browser/__tests__/ModelBrowser.test.tsx -t "phase A placeholder"`
Expected: FAIL on the first test.

- [ ] **Step 3: Replace the top-level loading branch in `ModelBrowser.tsx`.**

Replace lines 79-104 (the three early-return branches) with:

```tsx
if (error) {
  return (
    <div className="p-6 space-y-3">
      <p className="text-sm text-red-300">{error}</p>
      <button
        type="button"
        onClick={() => { void refresh() }}
        className="rounded border border-white/15 px-3 py-1 text-[12px] text-white/80 hover:bg-white/5"
      >
        Try again
      </button>
    </div>
  )
}

if (groups.length === 0 && loading) {
  return (
    <div
      data-testid="model-browser-phase-a"
      className="p-6 flex items-center gap-2 text-sm text-white/60"
    >
      <span
        className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-white/30 border-t-white/80"
        aria-hidden
      />
      <span>Lädt Verbindungen…</span>
    </div>
  )
}

if (groups.length === 0) {
  return (
    <div className="p-6 text-sm text-white/60">
      No LLM connection configured. Add one in the "LLM Providers" tab.
    </div>
  )
}
```

- [ ] **Step 4: Run the tests — both should pass.**

Run: `cd frontend && pnpm vitest run src/app/components/model-browser/__tests__/ModelBrowser.test.tsx -t "phase A placeholder"`
Expected: PASS.

- [ ] **Step 5: Run the whole ModelBrowser test file.**

Run: `cd frontend && pnpm vitest run src/app/components/model-browser/__tests__/ModelBrowser.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit.**

```bash
git add frontend/src/app/components/model-browser/ModelBrowser.tsx \
        frontend/src/app/components/model-browser/__tests__/ModelBrowser.test.tsx
git commit -m "Drive ModelBrowser phase-A placeholder off groups.length"
```

---

### Task 8: ConnectionGroup — render per-group loading body

**Files:**
- Modify: `frontend/src/app/components/model-browser/ModelBrowser.tsx` (`ConnectionGroup` props + body, lines 221-327)
- Modify: `frontend/src/app/components/model-browser/__tests__/ModelBrowser.test.tsx`

- [ ] **Step 1: Write a failing test that asserts a loading group renders a spinner and "Lädt Modelle…" text instead of the empty-hint.**

Add to `ModelBrowser.test.tsx`:

```ts
describe('ModelBrowser — per-group loading', () => {
  it('renders a spinner inside a group whose status is loading', async () => {
    hubState.groups = [
      {
        connection: makeConnection({ id: 'c1', display_name: 'Slow Co', slug: 'slow' }),
        status: 'loading',
        models: [],
      },
    ]

    const { ModelBrowser } = await import('../ModelBrowser')
    render(<ModelBrowser />)

    expect(screen.getByTestId('group-loading-c1')).toBeInTheDocument()
    expect(screen.queryByText(/No models listed/i)).toBeNull()
  })
})
```

- [ ] **Step 2: Run the test — it should fail (no such testid).**

Run: `cd frontend && pnpm vitest run src/app/components/model-browser/__tests__/ModelBrowser.test.tsx -t "per-group loading"`
Expected: FAIL.

- [ ] **Step 3: Extend `ConnectionGroupProps` and pass `status`/`error` through.**

In `ModelBrowser.tsx`, modify the props interface (around line 221-230):

```ts
interface ConnectionGroupProps {
  connectionId: string
  displayName: string
  slug: string
  status: 'loading' | 'ready' | 'error'
  error?: string
  models: EnrichedModelDto[]
  currentModelId?: string | null
  onSelect?: (model: EnrichedModelDto) => void
  onEdit: (model: EnrichedModelDto) => void
  onToggleFavourite: (model: EnrichedModelDto) => Promise<void>
}
```

Update the `ConnectionGroup` function signature to destructure `status` and `error`.

Update the call site in `ModelBrowser` (around line 192-204) to pass them:

```tsx
{filteredGroups.map((group) => (
  <ConnectionGroup
    key={group.connection.id}
    connectionId={group.connection.id}
    displayName={group.connection.display_name}
    slug={group.connection.slug}
    status={group.status}
    error={group.error}
    models={group.models}
    currentModelId={currentModelId}
    onSelect={onSelect}
    onEdit={(model) => setConfigModel(model)}
    onToggleFavourite={toggleFavourite}
  />
))}
```

- [ ] **Step 4: Replace the body of `ConnectionGroup` (the `!isCollapsed` branch, around lines 303-324) with a status-aware render.**

```tsx
{!isCollapsed && (
  status === 'loading' ? (
    <div
      data-testid={`group-loading-${connectionId}`}
      className="flex items-center gap-2 px-3 py-3 text-[12px] text-white/55"
    >
      <span
        className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-white/25 border-t-white/75"
        aria-hidden
      />
      <span>Lädt Modelle…</span>
    </div>
  ) : status === 'error' ? (
    <div
      data-testid={`group-error-${connectionId}`}
      className="px-3 py-3 text-[12px] text-red-300"
    >
      {error ?? 'Could not load models.'}{' '}
      <span className="text-white/45">
        Click <span className="font-mono text-white/65">⟳</span> to retry.
      </span>
    </div>
  ) : models.length === 0 ? (
    <p className="px-3 py-3 text-[12px] text-white/45">
      No models listed for this connection yet. Click{' '}
      <span className="font-mono text-white/65">⟳</span> to fetch from the
      upstream.
    </p>
  ) : (
    <ul className="divide-y divide-white/5 mt-1">
      {models.map((model) => (
        <ModelRow
          key={model.unique_id}
          model={model}
          isCurrent={model.unique_id === currentModelId}
          onSelect={onSelect}
          onEdit={() => onEdit(model)}
          onToggleFavourite={() => void onToggleFavourite(model)}
        />
      ))}
    </ul>
  )
)}
```

- [ ] **Step 5: Run the new test — should pass.**

Run: `cd frontend && pnpm vitest run src/app/components/model-browser/__tests__/ModelBrowser.test.tsx -t "per-group loading"`
Expected: PASS.

- [ ] **Step 6: Run the whole ModelBrowser test file (older tests with `status: 'ready'` mocks must still pass).**

Run: `cd frontend && pnpm vitest run src/app/components/model-browser/__tests__/ModelBrowser.test.tsx`
Expected: PASS.

- [ ] **Step 7: Commit.**

```bash
git add frontend/src/app/components/model-browser/ModelBrowser.tsx \
        frontend/src/app/components/model-browser/__tests__/ModelBrowser.test.tsx
git commit -m "Render per-group loading state in ConnectionGroup"
```

---

### Task 9: ConnectionGroup — render per-group error body

**Files:**
- Modify: `frontend/src/app/components/model-browser/__tests__/ModelBrowser.test.tsx` (test only — implementation already in place)

The error branch is already implemented as part of Task 8 step 4. Cover it with a test.

- [ ] **Step 1: Add a test for the error state.**

```ts
describe('ModelBrowser — per-group error', () => {
  it('renders the error message and retry hint when a group has status error', async () => {
    hubState.groups = [
      {
        connection: makeConnection({ id: 'c1', display_name: 'Broken' }),
        status: 'error',
        error: 'upstream 503',
        models: [],
      },
    ]

    const { ModelBrowser } = await import('../ModelBrowser')
    render(<ModelBrowser />)

    const node = screen.getByTestId('group-error-c1')
    expect(node).toBeInTheDocument()
    expect(node).toHaveTextContent('upstream 503')
    expect(node).toHaveTextContent(/retry/i)
  })
})
```

- [ ] **Step 2: Run the test — should pass (implementation is from Task 8).**

Run: `cd frontend && pnpm vitest run src/app/components/model-browser/__tests__/ModelBrowser.test.tsx -t "per-group error"`
Expected: PASS.

- [ ] **Step 3: Commit.**

```bash
git add frontend/src/app/components/model-browser/__tests__/ModelBrowser.test.tsx
git commit -m "Cover per-group error rendering with a test"
```

---

### Task 10: Keep loading/error groups visible through the filter pipeline

**Files:**
- Modify: `frontend/src/app/components/model-browser/ModelBrowser.tsx:54-70` (`filteredGroups`)
- Modify: `frontend/src/app/components/model-browser/__tests__/ModelBrowser.test.tsx`

- [ ] **Step 1: Write a failing test that asserts a loading group with zero models is visible even after the filter pipeline runs.**

```ts
describe('ModelBrowser — filter pipeline keeps non-ready groups', () => {
  it('keeps a loading group visible even when models are empty', async () => {
    hubState.groups = [
      {
        connection: makeConnection({ id: 'c1', display_name: 'LoadingCo' }),
        status: 'loading',
        models: [],
      },
      {
        connection: makeConnection({ id: 'c2', display_name: 'ErrorCo' }),
        status: 'error',
        error: 'oops',
        models: [],
      },
    ]

    const { ModelBrowser } = await import('../ModelBrowser')
    render(<ModelBrowser />)

    expect(screen.getByTestId('group-loading-c1')).toBeInTheDocument()
    expect(screen.getByTestId('group-error-c2')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run the test.**

Run: `cd frontend && pnpm vitest run src/app/components/model-browser/__tests__/ModelBrowser.test.tsx -t "filter pipeline"`
Expected result depends on whether the current `filteredGroups` keep-rule already keeps these. The current rule (lines 65-69) is:

```
.filter((g) => g.models.length > 0 || g.sourceEmpty)
```

`sourceEmpty` is `g.models.length === 0` from the source side, so it is `true` here too, which means **the test may already pass**. Run and see.

If it passes, skip steps 3-4 and just commit the test. If it fails (e.g. because grouping filtered out due to provider filter or some path), continue.

- [ ] **Step 3: If the test fails, change the keep-rule to be explicit about status.**

Replace the `.filter((g) => g.models.length > 0 || g.sourceEmpty)` clause with:

```ts
.filter((g) => g.status !== 'ready' || g.models.length > 0 || g.sourceEmpty)
```

And include `status` on the projection above so it survives the `.map` (the projection is already `{ connection, models, sourceEmpty }` — extend to `{ connection, status, error, models, sourceEmpty }`). Then also update the JSX call site to pass `group.status` / `group.error` from the projection.

- [ ] **Step 4: Re-run the test until it passes.**

Run: `cd frontend && pnpm vitest run src/app/components/model-browser/__tests__/ModelBrowser.test.tsx -t "filter pipeline"`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add frontend/src/app/components/model-browser/ModelBrowser.tsx \
        frontend/src/app/components/model-browser/__tests__/ModelBrowser.test.tsx
git commit -m "Keep loading and error groups visible through the filter pipeline"
```

---

### Task 11: Hide the filter bar during phase A

**Files:**
- Modify: `frontend/src/app/components/model-browser/ModelBrowser.tsx:108-185` (filter bar)
- Modify: `frontend/src/app/components/model-browser/__tests__/ModelBrowser.test.tsx`

- [ ] **Step 1: Write a failing test.**

```ts
describe('ModelBrowser — filter bar gating', () => {
  it('hides the filter bar during phase A', async () => {
    hubState.groups = []
    hubState.loading = true

    const { ModelBrowser } = await import('../ModelBrowser')
    render(<ModelBrowser />)

    expect(screen.queryByPlaceholderText(/search model name/i)).toBeNull()
  })

  it('shows the filter bar once groups are present', async () => {
    hubState.groups = [
      {
        connection: makeConnection({ id: 'c1' }),
        status: 'ready',
        models: [],
      },
    ]
    hubState.loading = false

    const { ModelBrowser } = await import('../ModelBrowser')
    render(<ModelBrowser />)

    expect(screen.getByPlaceholderText(/search model name/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run the tests.**

Run: `cd frontend && pnpm vitest run src/app/components/model-browser/__tests__/ModelBrowser.test.tsx -t "filter bar gating"`
Expected: the first test fails (phase-A early-return from Task 7 already hides the bar, but only because we early-return entirely; that **does** make the first test pass). The second should already pass.

If both pass, skip step 3 and just commit the test. If the first fails because the early-return changed, continue.

- [ ] **Step 3: If needed, adjust ModelBrowser to keep the filter bar conditionally hidden.**

(Most likely no code change required because the phase-A early-return from Task 7 already returns before the filter bar renders.)

- [ ] **Step 4: Run the full ModelBrowser test file.**

Run: `cd frontend && pnpm vitest run src/app/components/model-browser/__tests__/ModelBrowser.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add frontend/src/app/components/model-browser/__tests__/ModelBrowser.test.tsx \
        frontend/src/app/components/model-browser/ModelBrowser.tsx
git commit -m "Cover filter-bar gating during phase A"
```

---

### Task 12: Full verification — type check, full test run, manual smoke

**Files:** none

- [ ] **Step 1: Type-check the frontend.**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: PASS with no errors.

- [ ] **Step 2: Run the full frontend test suite.**

Run: `cd frontend && pnpm test --run`
Expected: PASS.

- [ ] **Step 3: Build the frontend (per CLAUDE.md "Build Verification").**

Run: `cd frontend && pnpm run build`
Expected: clean build.

- [ ] **Step 4: Manual smoke test — start the dev server.**

Run: `cd frontend && pnpm dev`

Open the app, log in, go to the Models tab in the user modal. Observe:

- Connection headers appear immediately (no long "Loading models…" pause).
- Each group shows the small spinner with "Lädt Modelle…" until its own fetch returns.
- Each group's models pop in independently as their fetch resolves.
- If a provider returns an error (you can simulate by temporarily breaking one connection's credentials), that group shows a red error message and a retry hint; the `⟳` button on that header re-runs.
- Other consumers still work: open a persona's `EditTab` and `OverviewTab` while the Models tab is loading — confirm no missing-model banner flashes.
- Open `UserModal` directly with no LLM connection configured — confirm the "no LLM connection" hint behaves as before.

- [ ] **Step 5: If any manual issue surfaces, fix and commit. Otherwise no commit needed for this task.**

---

## Self-review

**Spec coverage:**
- "Show each provider's models as soon as that provider responds" → Tasks 3, 8.
- "Show all configured providers immediately as headers" → Task 2 (skeleton), Task 7 (UI).
- "Surface per-provider load failures inline" → Tasks 4, 9.
- "Add a visible spinner" → Tasks 7, 8 (CSS spinner in placeholder and per-group loading body).
- "External loading semantics preserved" → Task 5.
- "Generation counter guards stale writes" → Task 6.
- "filteredGroups keeps loading/error groups visible" → Task 10.
- "Hide filter bar during phase A" → Task 11.
- Spec out-of-scope items (per-event scoping, skeleton placeholder rows, stale-while-revalidate) → not in any task.

**Placeholder scan:** No "TBD" / "TODO" / vague references. Every step shows the exact code or command.

**Type consistency:**
- `ConnectionModelGroup.status` defined in Task 1 as `'loading' | 'ready' | 'error'` and used consistently in every later task.
- `ConnectionModelGroup.error` is `string | undefined` (optional). Per-group `.then` clears it via `error: undefined`; `.catch` sets it.
- `ConnectionGroupProps` extended in Task 8 with the same `status`/`error` shape.
- Test mocks in `ModelBrowser.test.tsx` are updated to the new shape in Task 1 step 7.
- `useRef` import added in Task 6 step 3.

**Open items I considered and deliberately deferred:**
- `EditTab` / `OverviewTab` / `UserModal` regression tests — they would catch a future semantic break of `loading`, but Task 5's unit test covers the contract and the manual smoke test in Task 12 catches integration. Not worth a new test file.
- Per-event scoped refresh — explicitly out of scope per spec.
