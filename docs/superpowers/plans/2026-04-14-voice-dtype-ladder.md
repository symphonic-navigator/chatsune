# Voice Dtype Ladder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hard-coded per-device dtype selection in the voice worker with a capability-aware, per-model ladder that probes the browser's WebGPU adapter, tries dtypes in preference order, persists the winning decision per hardware fingerprint in IndexedDB, and logs every step to the console.

**Architecture:** Four new pure/infrastructure modules (`dtypeLadder`, `capabilityProbe`, `dtypeCache`, `voiceLadderRunner`) plus refactored `voiceWorker`, `voiceWorkerClient` and two engines. The client no longer picks a device — the worker decides, reports back a resolved `{ device, dtype, fromCache }` tuple. Spec: `docs/superpowers/specs/2026-04-14-voice-dtype-ladder-design.md`.

**Tech Stack:** TypeScript, Vitest, `@huggingface/transformers`, `kokoro-js`, `onnxruntime-web` (via transitive deps), IndexedDB (wrapped thinly), `fake-indexeddb` (new dev dep for tests).

---

## File Structure

**New:**
- `frontend/src/features/voice/infrastructure/dtypeLadder.ts` — `DtypeEntry` type, `WHISPER_LADDER`, `KOKORO_LADDER`, `filterLadder()`
- `frontend/src/features/voice/infrastructure/capabilityProbe.ts` — `VoiceCapabilities` type, `probeCapabilities()`, `computeFingerprint()`, `CACHE_VERSION`
- `frontend/src/features/voice/infrastructure/dtypeCache.ts` — `Decision` type, `getDecision()`, `putDecision()`, internal IDB open helper
- `frontend/src/features/voice/workers/voiceLadderRunner.ts` — generic `walkLadder<T>()` driving one ladder with a user-supplied loader + warmup
- `frontend/src/features/voice/infrastructure/__tests__/dtypeLadder.test.ts`
- `frontend/src/features/voice/infrastructure/__tests__/capabilityProbe.test.ts`
- `frontend/src/features/voice/infrastructure/__tests__/dtypeCache.test.ts`
- `frontend/src/features/voice/workers/__tests__/voiceLadderRunner.test.ts`

**Modified:**
- `frontend/src/features/voice/workers/voiceWorker.ts` — use `walkLadder`, drop `msg.device`, emit `resolved`
- `frontend/src/features/voice/workers/voiceWorkerClient.ts` — drop `device` param from `initSTT`/`initTTS`, receive `resolved`, expose it on return
- `frontend/src/features/voice/engines/whisperEngine.ts` — `init()` drops `device` param
- `frontend/src/features/voice/engines/kokoroEngine.ts` — `init()` drops `device` param
- `frontend/src/features/voice/stores/engineLoaderStore.ts` — stop calling `modelManager.detectDevice()`, call `init()` with no args
- `frontend/src/features/voice/hooks/useVoiceCapabilities.ts` — `VoiceDevice` becomes irrelevant for engine init; keep supported flags, drop `device` from return value
- `frontend/package.json` — add `fake-indexeddb` as devDependency

---

## Task 1: Add `fake-indexeddb` devDependency

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Install `fake-indexeddb`**

```bash
cd /home/chris/workspace/chatsune/frontend && pnpm add -D fake-indexeddb
```

Expected: `+ fake-indexeddb 6.x.x` shown in devDependencies.

- [ ] **Step 2: Commit**

```bash
cd /home/chris/workspace/chatsune && git add frontend/package.json frontend/pnpm-lock.yaml
git commit -m "Add fake-indexeddb dev dependency for voice dtype cache tests"
```

---

## Task 2: `dtypeLadder.ts` — types and ladder constants (no runtime logic yet)

**Files:**
- Create: `frontend/src/features/voice/infrastructure/dtypeLadder.ts`
- Create: `frontend/src/features/voice/infrastructure/__tests__/dtypeLadder.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/features/voice/infrastructure/__tests__/dtypeLadder.test.ts
import { describe, it, expect } from 'vitest'
import { filterLadder, WHISPER_LADDER, KOKORO_LADDER } from '../dtypeLadder'
import type { VoiceCapabilities } from '../capabilityProbe'

const baseCaps: VoiceCapabilities = {
  webgpu: true,
  shaderF16: true,
  adapterInfo: { vendor: 'test', architecture: 'arch' },
}

describe('filterLadder', () => {
  it('keeps every entry when both webgpu and shader-f16 are present', () => {
    expect(filterLadder(WHISPER_LADDER, baseCaps)).toEqual(WHISPER_LADDER)
  })

  it('strips shader-f16 entries when the feature is missing', () => {
    const caps = { ...baseCaps, shaderF16: false }
    const out = filterLadder(WHISPER_LADDER, caps)
    expect(out.some((e) => 'requires' in e && e.requires === 'shader-f16')).toBe(false)
    // non-f16 entries survive
    expect(out.some((e) => e.device === 'webgpu' && e.dtype === 'fp32')).toBe(true)
    expect(out.some((e) => e.device === 'webgpu' && e.dtype === 'q4')).toBe(true)
  })

  it('strips all webgpu entries when webgpu is unavailable', () => {
    const caps = { ...baseCaps, webgpu: false, shaderF16: false }
    const out = filterLadder(KOKORO_LADDER, caps)
    expect(out.every((e) => e.device === 'wasm')).toBe(true)
  })

  it('preserves the original ladder order', () => {
    const out = filterLadder(WHISPER_LADDER, baseCaps)
    expect(out[0]).toMatchObject({ device: 'webgpu', dtype: 'fp16' })
  })

  it('whisper ladder prefers fp16 over q4f16 (quality first)', () => {
    const fp16 = WHISPER_LADDER.findIndex((e) => e.device === 'webgpu' && e.dtype === 'fp16')
    const q4f16 = WHISPER_LADDER.findIndex((e) => e.device === 'webgpu' && e.dtype === 'q4f16')
    expect(fp16).toBeLessThan(q4f16)
  })

  it('kokoro ladder prefers q4f16 over fp16 (size first)', () => {
    const fp16 = KOKORO_LADDER.findIndex((e) => e.device === 'webgpu' && e.dtype === 'fp16')
    const q4f16 = KOKORO_LADDER.findIndex((e) => e.device === 'webgpu' && e.dtype === 'q4f16')
    expect(q4f16).toBeLessThan(fp16)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm vitest run src/features/voice/infrastructure/__tests__/dtypeLadder.test.ts`
Expected: FAIL — `Cannot find module '../dtypeLadder'`

- [ ] **Step 3: Write minimal implementation**

```ts
// frontend/src/features/voice/infrastructure/dtypeLadder.ts
import type { VoiceCapabilities } from './capabilityProbe'

export type DtypeEntry =
  | { device: 'webgpu'; dtype: 'q4f16' | 'fp16'; requires: 'shader-f16' }
  | { device: 'webgpu'; dtype: 'q4' | 'fp32' }
  | { device: 'wasm'; dtype: 'q8' | 'q4' | 'fp32' }

// Whisper: transcription quality over download size. On a GPU with
// fp16 compute, fp16 is preferred over q4f16; we only accept quantised
// weights when unavoidable.
export const WHISPER_LADDER: DtypeEntry[] = [
  { device: 'webgpu', dtype: 'fp16',  requires: 'shader-f16' },
  { device: 'webgpu', dtype: 'q4f16', requires: 'shader-f16' },
  { device: 'webgpu', dtype: 'fp32' },
  { device: 'webgpu', dtype: 'q4' },
  { device: 'wasm',   dtype: 'q8' },
  { device: 'wasm',   dtype: 'fp32' },
]

// Kokoro: synthesis tolerates quantisation well, so prefer the smallest
// GPU-native option first.
export const KOKORO_LADDER: DtypeEntry[] = [
  { device: 'webgpu', dtype: 'q4f16', requires: 'shader-f16' },
  { device: 'webgpu', dtype: 'fp16',  requires: 'shader-f16' },
  { device: 'webgpu', dtype: 'q4' },
  { device: 'webgpu', dtype: 'fp32' },
  { device: 'wasm',   dtype: 'q8' },
  { device: 'wasm',   dtype: 'fp32' },
]

export function filterLadder(
  ladder: readonly DtypeEntry[],
  caps: VoiceCapabilities,
): DtypeEntry[] {
  return ladder.filter((entry) => {
    if (entry.device === 'webgpu' && !caps.webgpu) return false
    if ('requires' in entry && entry.requires === 'shader-f16' && !caps.shaderF16) return false
    return true
  })
}
```

- [ ] **Step 4: Stub `capabilityProbe` just enough for the import to resolve**

Task 3 replaces this stub. For now:

```ts
// frontend/src/features/voice/infrastructure/capabilityProbe.ts
export interface VoiceCapabilities {
  webgpu: boolean
  shaderF16: boolean
  adapterInfo: { vendor: string; architecture: string } | null
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm vitest run src/features/voice/infrastructure/__tests__/dtypeLadder.test.ts`
Expected: PASS, 6 tests

- [ ] **Step 6: Commit**

```bash
cd /home/chris/workspace/chatsune && \
  git add frontend/src/features/voice/infrastructure/dtypeLadder.ts \
          frontend/src/features/voice/infrastructure/capabilityProbe.ts \
          frontend/src/features/voice/infrastructure/__tests__/dtypeLadder.test.ts
git commit -m "Add voice dtype ladder constants and filter"
```

---

## Task 3: `capabilityProbe.ts` — probe and fingerprint

**Files:**
- Modify: `frontend/src/features/voice/infrastructure/capabilityProbe.ts`
- Create: `frontend/src/features/voice/infrastructure/__tests__/capabilityProbe.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/features/voice/infrastructure/__tests__/capabilityProbe.test.ts
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { probeCapabilities, computeFingerprint, CACHE_VERSION } from '../capabilityProbe'

function installGpu(
  features: string[] | null,
  info: { vendor: string; architecture: string } | null,
) {
  const adapter = features === null ? null : {
    features: new Set(features),
    info,
  }
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true,
    value: {
      gpu: {
        requestAdapter: vi.fn().mockResolvedValue(adapter),
      },
    },
  })
}

function removeGpu() {
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true,
    value: {},
  })
}

describe('probeCapabilities', () => {
  beforeEach(() => {
    // ensure we re-probe between tests (implementation memoises)
    // expose reset from the module
  })

  it('reports webgpu=false when navigator.gpu is missing', async () => {
    removeGpu()
    const caps = await probeCapabilities({ forceFresh: true })
    expect(caps.webgpu).toBe(false)
    expect(caps.shaderF16).toBe(false)
    expect(caps.adapterInfo).toBeNull()
  })

  it('reports webgpu=false when requestAdapter resolves null', async () => {
    installGpu(null, null)
    const caps = await probeCapabilities({ forceFresh: true })
    expect(caps.webgpu).toBe(false)
  })

  it('reports shaderF16=true when the adapter advertises it', async () => {
    installGpu(['shader-f16'], { vendor: 'amd', architecture: 'rdna3' })
    const caps = await probeCapabilities({ forceFresh: true })
    expect(caps.webgpu).toBe(true)
    expect(caps.shaderF16).toBe(true)
    expect(caps.adapterInfo).toEqual({ vendor: 'amd', architecture: 'rdna3' })
  })

  it('reports shaderF16=false when the feature set omits it', async () => {
    installGpu([], { vendor: 'nvidia', architecture: 'ampere' })
    const caps = await probeCapabilities({ forceFresh: true })
    expect(caps.webgpu).toBe(true)
    expect(caps.shaderF16).toBe(false)
  })

  it('memoises within a session — second call does not reprobe', async () => {
    installGpu(['shader-f16'], { vendor: 'amd', architecture: 'rdna3' })
    const first = await probeCapabilities({ forceFresh: true })
    // install a different GPU state — probeCapabilities should ignore it
    installGpu([], { vendor: 'other', architecture: 'other' })
    const second = await probeCapabilities()
    expect(second).toBe(first) // same reference
  })
})

describe('computeFingerprint', () => {
  it('uses wasm token when webgpu is false', () => {
    const fp = computeFingerprint({ webgpu: false, shaderF16: false, adapterInfo: null })
    expect(fp).toBe(`wasm/v${CACHE_VERSION}`)
  })

  it('encodes vendor, architecture, and shader-f16 flag for webgpu', () => {
    const fp = computeFingerprint({
      webgpu: true,
      shaderF16: true,
      adapterInfo: { vendor: 'amd', architecture: 'rdna3' },
    })
    expect(fp).toBe(`webgpu/amd/rdna3/f16:true/v${CACHE_VERSION}`)
  })

  it('falls back to "unknown" tokens when adapterInfo is null', () => {
    const fp = computeFingerprint({
      webgpu: true,
      shaderF16: false,
      adapterInfo: null,
    })
    expect(fp).toBe(`webgpu/unknown/unknown/f16:false/v${CACHE_VERSION}`)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm vitest run src/features/voice/infrastructure/__tests__/capabilityProbe.test.ts`
Expected: FAIL — `probeCapabilities`/`computeFingerprint` not exported

- [ ] **Step 3: Write implementation**

Replace the stub from Task 2 with:

```ts
// frontend/src/features/voice/infrastructure/capabilityProbe.ts

// Bump when the ladder, this module, or any relevant library
// (transformers.js / kokoro-js / onnxruntime-web) changes in a way that
// could invalidate previously cached dtype decisions.
export const CACHE_VERSION = 1

export interface VoiceCapabilities {
  webgpu: boolean
  shaderF16: boolean
  adapterInfo: { vendor: string; architecture: string } | null
}

let cached: VoiceCapabilities | null = null

export async function probeCapabilities(
  opts: { forceFresh?: boolean } = {},
): Promise<VoiceCapabilities> {
  if (cached && !opts.forceFresh) return cached

  const nav = typeof navigator !== 'undefined' ? navigator : undefined
  const gpu = (nav as unknown as { gpu?: { requestAdapter: () => Promise<unknown> } } | undefined)?.gpu

  if (!gpu) {
    cached = { webgpu: false, shaderF16: false, adapterInfo: null }
    return cached
  }

  try {
    const adapter = await gpu.requestAdapter() as {
      features: Set<string>
      info: { vendor: string; architecture: string } | null
    } | null

    if (!adapter) {
      cached = { webgpu: false, shaderF16: false, adapterInfo: null }
      return cached
    }

    cached = {
      webgpu: true,
      shaderF16: adapter.features.has('shader-f16'),
      adapterInfo: adapter.info ?? null,
    }
    return cached
  } catch {
    cached = { webgpu: false, shaderF16: false, adapterInfo: null }
    return cached
  }
}

export function computeFingerprint(caps: VoiceCapabilities): string {
  if (!caps.webgpu) return `wasm/v${CACHE_VERSION}`
  const vendor = caps.adapterInfo?.vendor ?? 'unknown'
  const arch = caps.adapterInfo?.architecture ?? 'unknown'
  return `webgpu/${vendor}/${arch}/f16:${caps.shaderF16}/v${CACHE_VERSION}`
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm vitest run src/features/voice/infrastructure/__tests__/capabilityProbe.test.ts`
Expected: PASS, 8 tests

- [ ] **Step 5: Run type check**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc -b`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
cd /home/chris/workspace/chatsune && \
  git add frontend/src/features/voice/infrastructure/capabilityProbe.ts \
          frontend/src/features/voice/infrastructure/__tests__/capabilityProbe.test.ts
git commit -m "Add WebGPU capability probe and fingerprint"
```

---

## Task 4: `dtypeCache.ts` — IndexedDB-backed decision store

**Files:**
- Create: `frontend/src/features/voice/infrastructure/dtypeCache.ts`
- Create: `frontend/src/features/voice/infrastructure/__tests__/dtypeCache.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/features/voice/infrastructure/__tests__/dtypeCache.test.ts
import { describe, it, expect, beforeEach } from 'vitest'
import 'fake-indexeddb/auto'
import { getDecision, putDecision, _resetForTests } from '../dtypeCache'

describe('dtypeCache', () => {
  beforeEach(async () => {
    await _resetForTests()
  })

  it('returns null on cache miss', async () => {
    const d = await getDecision('whisper', 'webgpu/amd/rdna3/f16:true/v1')
    expect(d).toBeNull()
  })

  it('returns the stored decision on hit', async () => {
    await putDecision('whisper', 'webgpu/amd/rdna3/f16:true/v1', {
      device: 'webgpu',
      dtype: 'fp16',
    })
    const d = await getDecision('whisper', 'webgpu/amd/rdna3/f16:true/v1')
    expect(d).toMatchObject({ device: 'webgpu', dtype: 'fp16' })
    expect(typeof d?.decidedAt).toBe('string')
  })

  it('overwrites an existing entry for the same key', async () => {
    const key = 'webgpu/amd/rdna3/f16:true/v1'
    await putDecision('whisper', key, { device: 'webgpu', dtype: 'fp16' })
    await putDecision('whisper', key, { device: 'webgpu', dtype: 'q4' })
    const d = await getDecision('whisper', key)
    expect(d?.dtype).toBe('q4')
  })

  it('isolates decisions per model', async () => {
    const key = 'webgpu/amd/rdna3/f16:true/v1'
    await putDecision('whisper', key, { device: 'webgpu', dtype: 'fp16' })
    await putDecision('kokoro', key, { device: 'webgpu', dtype: 'q4f16' })
    expect((await getDecision('whisper', key))?.dtype).toBe('fp16')
    expect((await getDecision('kokoro', key))?.dtype).toBe('q4f16')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm vitest run src/features/voice/infrastructure/__tests__/dtypeCache.test.ts`
Expected: FAIL — module does not exist

- [ ] **Step 3: Write implementation**

```ts
// frontend/src/features/voice/infrastructure/dtypeCache.ts
import { CACHE_VERSION } from './capabilityProbe'

const DB_NAME = 'chatsune-voice-meta'
const STORE = 'dtypeDecisions'
const DB_VERSION = 1

export interface Decision {
  device: 'webgpu' | 'wasm'
  dtype: string
  decidedAt: string
  cacheVersion: number
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE)
      }
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

function key(modelId: string, fingerprint: string): string {
  return `${modelId}:${fingerprint}`
}

export async function getDecision(
  modelId: string,
  fingerprint: string,
): Promise<Decision | null> {
  const db = await openDb()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readonly')
    const req = tx.objectStore(STORE).get(key(modelId, fingerprint))
    req.onsuccess = () => {
      const v = req.result as Decision | undefined
      if (!v) return resolve(null)
      if (v.cacheVersion !== CACHE_VERSION) return resolve(null)
      resolve(v)
    }
    req.onerror = () => reject(req.error)
  })
}

export async function putDecision(
  modelId: string,
  fingerprint: string,
  choice: { device: 'webgpu' | 'wasm'; dtype: string },
): Promise<void> {
  const db = await openDb()
  const record: Decision = {
    ...choice,
    decidedAt: new Date().toISOString(),
    cacheVersion: CACHE_VERSION,
  }
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite')
    tx.objectStore(STORE).put(record, key(modelId, fingerprint))
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error)
  })
}

// Test-only: wipe the store so each test starts clean.
export async function _resetForTests(): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const req = indexedDB.deleteDatabase(DB_NAME)
    req.onsuccess = () => resolve()
    req.onerror = () => reject(req.error)
    req.onblocked = () => resolve()
  })
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm vitest run src/features/voice/infrastructure/__tests__/dtypeCache.test.ts`
Expected: PASS, 4 tests

- [ ] **Step 5: Commit**

```bash
cd /home/chris/workspace/chatsune && \
  git add frontend/src/features/voice/infrastructure/dtypeCache.ts \
          frontend/src/features/voice/infrastructure/__tests__/dtypeCache.test.ts
git commit -m "Add IndexedDB-backed dtype decision cache"
```

---

## Task 5: `voiceLadderRunner.ts` — generic ladder walker

**Files:**
- Create: `frontend/src/features/voice/workers/voiceLadderRunner.ts`
- Create: `frontend/src/features/voice/workers/__tests__/voiceLadderRunner.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/features/voice/workers/__tests__/voiceLadderRunner.test.ts
import { describe, it, expect, vi } from 'vitest'
import { walkLadder } from '../voiceLadderRunner'
import type { DtypeEntry } from '../../infrastructure/dtypeLadder'

const LADDER: DtypeEntry[] = [
  { device: 'webgpu', dtype: 'fp16',  requires: 'shader-f16' },
  { device: 'webgpu', dtype: 'fp32' },
  { device: 'wasm',   dtype: 'fp32' },
]

describe('walkLadder', () => {
  it('returns the first successful step', async () => {
    const load = vi.fn().mockResolvedValue('model')
    const warmup = vi.fn().mockResolvedValue(undefined)

    const result = await walkLadder({
      ladder: LADDER,
      load,
      warmup,
      collectGpuErrors: async () => [],
    })

    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.entry).toEqual(LADDER[0])
      expect(result.model).toBe('model')
      expect(result.attempts).toHaveLength(1)
      expect(result.attempts[0]?.outcome).toBe('ok')
    }
    expect(load).toHaveBeenCalledTimes(1)
  })

  it('advances when load throws', async () => {
    const load = vi.fn()
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValueOnce('model')
    const warmup = vi.fn().mockResolvedValue(undefined)

    const result = await walkLadder({
      ladder: LADDER,
      load,
      warmup,
      collectGpuErrors: async () => [],
    })

    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.entry).toEqual(LADDER[1])
      expect(result.attempts).toHaveLength(2)
      expect(result.attempts[0]?.outcome).toBe('load-failed')
    }
  })

  it('advances when warmup throws', async () => {
    const load = vi.fn().mockResolvedValue('model')
    const warmup = vi.fn()
      .mockRejectedValueOnce(new Error('warmup-boom'))
      .mockResolvedValueOnce(undefined)

    const result = await walkLadder({
      ladder: LADDER,
      load,
      warmup,
      collectGpuErrors: async () => [],
    })

    expect(result.ok).toBe(true)
    if (result.ok) expect(result.entry).toEqual(LADDER[1])
  })

  it('advances when collectGpuErrors returns a non-empty array', async () => {
    const load = vi.fn().mockResolvedValue('model')
    const warmup = vi.fn().mockResolvedValue(undefined)

    const calls: number[] = []
    const collectGpuErrors = vi.fn(async () => {
      calls.push(calls.length)
      return calls.length === 1 ? ['GPUValidationError: Add'] : []
    })

    const result = await walkLadder({
      ladder: LADDER,
      load,
      warmup,
      collectGpuErrors,
    })

    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.entry).toEqual(LADDER[1])
      expect(result.attempts[0]?.outcome).toBe('gpu-error')
    }
  })

  it('returns ok=false when every step fails', async () => {
    const load = vi.fn().mockRejectedValue(new Error('boom'))
    const warmup = vi.fn()

    const result = await walkLadder({
      ladder: LADDER,
      load,
      warmup,
      collectGpuErrors: async () => [],
    })

    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.attempts).toHaveLength(LADDER.length)
      expect(result.attempts.every((a) => a.outcome !== 'ok')).toBe(true)
    }
  })

  it('invokes a logger for every attempt', async () => {
    const logs: string[] = []
    const load = vi.fn().mockResolvedValue('model')
    const warmup = vi.fn().mockResolvedValue(undefined)

    await walkLadder({
      ladder: LADDER,
      load,
      warmup,
      collectGpuErrors: async () => [],
      log: (line) => logs.push(line),
    })

    expect(logs.some((l) => l.includes('webgpu/fp16'))).toBe(true)
    expect(logs.some((l) => l.includes('OK'))).toBe(true)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm vitest run src/features/voice/workers/__tests__/voiceLadderRunner.test.ts`
Expected: FAIL — module not found

- [ ] **Step 3: Write implementation**

```ts
// frontend/src/features/voice/workers/voiceLadderRunner.ts
import type { DtypeEntry } from '../infrastructure/dtypeLadder'

export type AttemptOutcome = 'ok' | 'load-failed' | 'warmup-failed' | 'gpu-error'

export interface Attempt {
  entry: DtypeEntry
  outcome: AttemptOutcome
  detail?: string
}

export interface WalkOk<T> {
  ok: true
  entry: DtypeEntry
  model: T
  attempts: Attempt[]
}

export interface WalkFailed {
  ok: false
  attempts: Attempt[]
}

export type WalkResult<T> = WalkOk<T> | WalkFailed

export interface WalkOptions<T> {
  ladder: readonly DtypeEntry[]
  /** Load the model for this entry. May throw on load failure. */
  load: (entry: DtypeEntry) => Promise<T>
  /** Run a quick warmup against the loaded model. May throw on failure. */
  warmup: (entry: DtypeEntry, model: T) => Promise<void>
  /** Return any WebGPU uncaptured errors that occurred during load+warmup. */
  collectGpuErrors: (entry: DtypeEntry) => Promise<string[]>
  /** Optional logger for per-step trace output. */
  log?: (line: string) => void
}

function formatEntry(e: DtypeEntry): string {
  return `${e.device}/${e.dtype}`
}

export async function walkLadder<T>(opts: WalkOptions<T>): Promise<WalkResult<T>> {
  const { ladder, load, warmup, collectGpuErrors, log } = opts
  const attempts: Attempt[] = []

  for (const entry of ladder) {
    log?.(`try ${formatEntry(entry)}`)
    let model: T
    try {
      model = await load(entry)
    } catch (err) {
      attempts.push({ entry, outcome: 'load-failed', detail: String(err) })
      log?.(`  ${formatEntry(entry)} — LOAD FAILED: ${String(err)}`)
      continue
    }

    try {
      await warmup(entry, model)
    } catch (err) {
      attempts.push({ entry, outcome: 'warmup-failed', detail: String(err) })
      log?.(`  ${formatEntry(entry)} — WARMUP FAILED: ${String(err)}`)
      continue
    }

    const gpuErrors = await collectGpuErrors(entry)
    if (gpuErrors.length > 0) {
      attempts.push({ entry, outcome: 'gpu-error', detail: gpuErrors.join('; ') })
      log?.(`  ${formatEntry(entry)} — GPU ERROR: ${gpuErrors.join('; ')}`)
      continue
    }

    attempts.push({ entry, outcome: 'ok' })
    log?.(`  ${formatEntry(entry)} — OK`)
    return { ok: true, entry, model, attempts }
  }

  return { ok: false, attempts }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm vitest run src/features/voice/workers/__tests__/voiceLadderRunner.test.ts`
Expected: PASS, 6 tests

- [ ] **Step 5: Run full test suite so far + tsc**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm vitest run src/features/voice/ && pnpm tsc -b`
Expected: PASS, no TS errors

- [ ] **Step 6: Commit**

```bash
cd /home/chris/workspace/chatsune && \
  git add frontend/src/features/voice/workers/voiceLadderRunner.ts \
          frontend/src/features/voice/workers/__tests__/voiceLadderRunner.test.ts
git commit -m "Add generic ladder walker for voice dtype selection"
```

---

## Task 6: Rewire `voiceWorker.ts` to use the ladder

**Files:**
- Modify: `frontend/src/features/voice/workers/voiceWorker.ts`

This task has no unit tests (worker is integration-tested manually in the browser at Task 10).

- [ ] **Step 1: Replace the init-stt and init-tts handlers to use walkLadder**

Full new content for `frontend/src/features/voice/workers/voiceWorker.ts`:

```ts
/**
 * Voice inference Web Worker.
 *
 * Runs Whisper (STT) and Kokoro (TTS) off the main thread so the UI
 * stays responsive during inference. Device + dtype selection is done
 * inside the worker via a capability-aware ladder; the client only asks
 * for "init stt" / "init tts" and receives the resolved tuple back.
 */
import {
  pipeline,
  env,
  type AutomaticSpeechRecognitionPipeline,
} from '@huggingface/transformers'
import { KokoroTTS } from 'kokoro-js'
import {
  WHISPER_LADDER,
  KOKORO_LADDER,
  filterLadder,
  type DtypeEntry,
} from '../infrastructure/dtypeLadder'
import {
  probeCapabilities,
  computeFingerprint,
} from '../infrastructure/capabilityProbe'
import { getDecision, putDecision } from '../infrastructure/dtypeCache'
import { walkLadder, type WalkResult } from './voiceLadderRunner'

const log = (msg: string, ...args: unknown[]) => console.log(`[VoiceWorker] ${msg}`, ...args)

// ── State ──

let sttPipe: AutomaticSpeechRecognitionPipeline | null = null
let tts: KokoroTTS | null = null

// ── Voice presets (must match kokoroEngine.ts) ──

const KOKORO_VOICES = [
  { id: 'af_heart', name: 'Heart (Female)', language: 'en', gender: 'female' },
  { id: 'af_bella', name: 'Bella (Female)', language: 'en', gender: 'female' },
  { id: 'af_sarah', name: 'Sarah (Female)', language: 'en', gender: 'female' },
  { id: 'af_nicole', name: 'Nicole (Female)', language: 'en', gender: 'female' },
  { id: 'af_sky', name: 'Sky (Female)', language: 'en', gender: 'female' },
  { id: 'am_adam', name: 'Adam (Male)', language: 'en', gender: 'male' },
  { id: 'am_michael', name: 'Michael (Male)', language: 'en', gender: 'male' },
  { id: 'bf_emma', name: 'Emma (British F)', language: 'en', gender: 'female' },
  { id: 'bf_isabella', name: 'Isabella (British F)', language: 'en', gender: 'female' },
  { id: 'bm_george', name: 'George (British M)', language: 'en', gender: 'male' },
  { id: 'bm_lewis', name: 'Lewis (British M)', language: 'en', gender: 'male' },
] as const

// ── WebGPU uncaptured-error capture ──
//
// ORT's JSEP backend holds a single shared GPUDevice across sessions.
// We hook its `uncapturederror` event each time we try a webgpu step
// so validation errors raised during load/warmup surface as a failure.

interface GpuErrorCapture {
  errors: string[]
  detach: () => void
}

function attachGpuErrorListener(): GpuErrorCapture {
  const ortEnv = env as unknown as { webgpu?: { device?: GPUDevice | null } }
  const device = ortEnv.webgpu?.device ?? null
  const errors: string[] = []
  if (!device) {
    return { errors, detach: () => {} }
  }
  const handler = (evt: Event) => {
    const ge = evt as unknown as { error: { message: string } }
    errors.push(ge.error?.message ?? 'unknown WebGPU error')
  }
  device.addEventListener('uncapturederror', handler as EventListener)
  return {
    errors,
    detach: () => device.removeEventListener('uncapturederror', handler as EventListener),
  }
}

// ── Ladder-driven init ──

async function resolveAndLoadWhisper(): Promise<{
  pipe: AutomaticSpeechRecognitionPipeline
  entry: DtypeEntry
  fromCache: boolean
}> {
  const caps = await probeCapabilities()
  const fp = computeFingerprint(caps)
  log('whisper: capabilities=%o fingerprint=%s', caps, fp)

  const cached = await getDecision('whisper', fp)
  if (cached) {
    log('whisper: cache HIT → %s/%s, loading...', cached.device, cached.dtype)
    try {
      const pipe = await loadWhisper(cached as unknown as DtypeEntry)
      await warmupWhisper(pipe)
      log('whisper: LOADED device=%s dtype=%s (fromCache=true)', cached.device, cached.dtype)
      return { pipe, entry: cached as unknown as DtypeEntry, fromCache: true }
    } catch (err) {
      log('whisper: cache hit failed (%s), falling through to ladder', String(err))
    }
  } else {
    log('whisper: cache MISS, walking ladder')
  }

  const ladder = filterLadder(WHISPER_LADDER, caps)
  let capture: GpuErrorCapture | null = null
  const result: WalkResult<AutomaticSpeechRecognitionPipeline> = await walkLadder({
    ladder,
    load: async (entry) => {
      capture?.detach()
      capture = entry.device === 'webgpu' ? attachGpuErrorListener() : { errors: [], detach: () => {} }
      return loadWhisper(entry)
    },
    warmup: async (_entry, pipe) => { await warmupWhisper(pipe) },
    collectGpuErrors: async () => {
      await new Promise<void>((r) => setTimeout(r, 0))
      const errs = capture?.errors.slice() ?? []
      capture?.detach()
      capture = null
      return errs
    },
    log: (line) => log('whisper: %s', line),
  })

  if (!result.ok) {
    throw new Error(`whisper: every ladder step failed — ${JSON.stringify(result.attempts)}`)
  }

  await putDecision('whisper', fp, { device: result.entry.device, dtype: result.entry.dtype })
  log('whisper: LOADED device=%s dtype=%s (fromCache=false)', result.entry.device, result.entry.dtype)
  return { pipe: result.model, entry: result.entry, fromCache: false }
}

async function loadWhisper(entry: DtypeEntry): Promise<AutomaticSpeechRecognitionPipeline> {
  return await pipeline('automatic-speech-recognition', 'onnx-community/whisper-tiny', {
    device: entry.device,
    dtype: entry.dtype,
  }) as AutomaticSpeechRecognitionPipeline
}

async function warmupWhisper(pipe: AutomaticSpeechRecognitionPipeline): Promise<void> {
  // 1 second of silence at 16 kHz
  const silence = new Float32Array(16_000)
  await pipe(silence, { language: 'en', return_timestamps: false })
}

async function resolveAndLoadKokoro(): Promise<{
  tts: KokoroTTS
  entry: DtypeEntry
  fromCache: boolean
}> {
  const caps = await probeCapabilities()
  const fp = computeFingerprint(caps)
  log('kokoro: capabilities=%o fingerprint=%s', caps, fp)

  const cached = await getDecision('kokoro', fp)
  if (cached) {
    log('kokoro: cache HIT → %s/%s, loading...', cached.device, cached.dtype)
    try {
      const ttsInst = await loadKokoro(cached as unknown as DtypeEntry)
      await warmupKokoro(ttsInst)
      log('kokoro: LOADED device=%s dtype=%s (fromCache=true)', cached.device, cached.dtype)
      return { tts: ttsInst, entry: cached as unknown as DtypeEntry, fromCache: true }
    } catch (err) {
      log('kokoro: cache hit failed (%s), falling through to ladder', String(err))
    }
  } else {
    log('kokoro: cache MISS, walking ladder')
  }

  const ladder = filterLadder(KOKORO_LADDER, caps)
  let capture: GpuErrorCapture | null = null
  const result: WalkResult<KokoroTTS> = await walkLadder({
    ladder,
    load: async (entry) => {
      capture?.detach()
      capture = entry.device === 'webgpu' ? attachGpuErrorListener() : { errors: [], detach: () => {} }
      return loadKokoro(entry)
    },
    warmup: async (_entry, inst) => { await warmupKokoro(inst) },
    collectGpuErrors: async () => {
      await new Promise<void>((r) => setTimeout(r, 0))
      const errs = capture?.errors.slice() ?? []
      capture?.detach()
      capture = null
      return errs
    },
    log: (line) => log('kokoro: %s', line),
  })

  if (!result.ok) {
    throw new Error(`kokoro: every ladder step failed — ${JSON.stringify(result.attempts)}`)
  }

  await putDecision('kokoro', fp, { device: result.entry.device, dtype: result.entry.dtype })
  log('kokoro: LOADED device=%s dtype=%s (fromCache=false)', result.entry.device, result.entry.dtype)
  return { tts: result.model, entry: result.entry, fromCache: false }
}

async function loadKokoro(entry: DtypeEntry): Promise<KokoroTTS> {
  return KokoroTTS.from_pretrained('onnx-community/Kokoro-82M-v1.0-ONNX', {
    device: entry.device,
    dtype: entry.dtype as 'fp32' | 'fp16' | 'q8' | 'q4' | 'q4f16',
  })
}

async function warmupKokoro(inst: KokoroTTS): Promise<void> {
  await inst.generate('test', {
    voice: 'af_heart' as NonNullable<Parameters<typeof inst.generate>[1]>['voice'],
  })
}

// ── Message handling ──

self.onmessage = async (e: MessageEvent) => {
  const msg = e.data

  switch (msg.type) {
    case 'init-stt': {
      log('init-stt start')
      try {
        const { pipe, entry, fromCache } = await resolveAndLoadWhisper()
        sttPipe = pipe
        self.postMessage({
          type: 'init-stt-done',
          resolved: { device: entry.device, dtype: entry.dtype, fromCache },
        })
      } catch (err) {
        log('init-stt error:', err)
        self.postMessage({ type: 'init-stt-error', error: String(err) })
      }
      break
    }

    case 'init-tts': {
      log('init-tts start')
      try {
        const { tts: inst, entry, fromCache } = await resolveAndLoadKokoro()
        tts = inst
        self.postMessage({
          type: 'init-tts-done',
          voices: KOKORO_VOICES,
          resolved: { device: entry.device, dtype: entry.dtype, fromCache },
        })
      } catch (err) {
        log('init-tts error:', err)
        self.postMessage({ type: 'init-tts-error', error: String(err) })
      }
      break
    }

    case 'transcribe': {
      log('transcribe start, id=%s, audioLen=%d', msg.id, msg.audio?.length ?? 0)
      if (!sttPipe) {
        self.postMessage({ type: 'transcribe-error', id: msg.id, error: 'STT not initialised' })
        break
      }
      try {
        const t0 = performance.now()
        const result = await sttPipe(msg.audio, {
          language: msg.language ?? 'en',
          return_timestamps: true,
        })
        const elapsed = Math.round(performance.now() - t0)
        const output = result as { text: string; chunks?: Array<{ text: string; timestamp: [number, number] }> }
        log('transcribe done, id=%s, %dms, text="%s"', msg.id, elapsed, output.text.trim().slice(0, 60))
        self.postMessage({
          type: 'transcribe-done',
          id: msg.id,
          text: output.text.trim(),
          language: msg.language ?? 'en',
          segments: output.chunks?.map((c) => ({ text: c.text, start: c.timestamp[0], end: c.timestamp[1] })),
        })
      } catch (err) {
        log('transcribe error, id=%s:', msg.id, err)
        self.postMessage({ type: 'transcribe-error', id: msg.id, error: String(err) })
      }
      break
    }

    case 'synthesise': {
      log('synthesise start, id=%s, text="%s", voice=%s', msg.id, msg.text.slice(0, 40), msg.voiceId)
      if (!tts) {
        self.postMessage({ type: 'synthesise-error', id: msg.id, error: 'TTS not initialised' })
        break
      }
      try {
        const t0 = performance.now()
        const result = await tts.generate(msg.text, {
          voice: msg.voiceId as NonNullable<Parameters<typeof tts.generate>[1]>['voice'],
        })
        const audio = result.audio as unknown as Float32Array
        const elapsed = Math.round(performance.now() - t0)
        log('synthesise done, id=%s, %dms, audioLen=%d', msg.id, elapsed, audio.length)
        self.postMessage(
          { type: 'synthesise-done', id: msg.id, audio },
          { transfer: [audio.buffer] },
        )
      } catch (err) {
        log('synthesise error, id=%s:', msg.id, err)
        self.postMessage({ type: 'synthesise-error', id: msg.id, error: String(err) })
      }
      break
    }
  }
}
```

- [ ] **Step 2: Type-check**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc -b`
Expected: no errors

- [ ] **Step 3: Commit**

```bash
cd /home/chris/workspace/chatsune && git add frontend/src/features/voice/workers/voiceWorker.ts
git commit -m "Drive voice worker dtype choice with capability-aware ladder"
```

---

## Task 7: Update `voiceWorkerClient.ts` — drop device param, expose resolved

**Files:**
- Modify: `frontend/src/features/voice/workers/voiceWorkerClient.ts`

- [ ] **Step 1: Replace `initSTT` and `initTTS` signatures**

Full new content for `frontend/src/features/voice/workers/voiceWorkerClient.ts`:

```ts
/**
 * Main-thread client for the voice inference Web Worker.
 *
 * Provides Promise-based methods that match the STTEngine/TTSEngine
 * interfaces. All heavy inference — including device + dtype selection —
 * runs in the worker. This class only passes messages and surfaces the
 * resolved `{ device, dtype, fromCache }` tuple back to callers.
 */
import type { VoicePreset } from '../types'

const log = (msg: string, ...args: unknown[]) => console.log(`[VoiceClient] ${msg}`, ...args)

type PendingResolve = { resolve: (value: unknown) => void; reject: (reason: unknown) => void }

export interface ResolvedDtype {
  device: 'webgpu' | 'wasm'
  dtype: string
  fromCache: boolean
}

export interface SttInitResult {
  resolved: ResolvedDtype
}

export interface TtsInitResult {
  voices: VoicePreset[]
  resolved: ResolvedDtype
}

class VoiceWorkerClient {
  private worker: Worker | null = null
  private pending = new Map<string, PendingResolve>()
  private nextId = 0
  private initCallbacks: Record<string, PendingResolve> = {}

  private getWorker(): Worker {
    if (!this.worker) {
      log('spawning worker')
      this.worker = new Worker(
        new URL('./voiceWorker.ts', import.meta.url),
        { type: 'module' },
      )
      this.worker.onmessage = (e) => this.handleMessage(e.data)
      this.worker.onerror = (e) => {
        console.error('[VoiceClient] Worker error:', e)
      }
    }
    return this.worker
  }

  private handleMessage(msg: Record<string, unknown>): void {
    switch (msg.type) {
      case 'init-stt-done': {
        const resolved = msg.resolved as ResolvedDtype | undefined
        log('init-stt-done: %o', resolved)
        this.initCallbacks['stt']?.resolve({ resolved } satisfies SttInitResult)
        delete this.initCallbacks['stt']
        break
      }
      case 'init-stt-error':
        log('init-stt-error: %s', msg.error)
        this.initCallbacks['stt']?.reject(new Error(msg.error as string))
        delete this.initCallbacks['stt']
        break
      case 'init-tts-done': {
        const resolved = msg.resolved as ResolvedDtype | undefined
        log('init-tts-done: %o', resolved)
        this.initCallbacks['tts']?.resolve({
          voices: msg.voices as VoicePreset[],
          resolved,
        } satisfies TtsInitResult)
        delete this.initCallbacks['tts']
        break
      }
      case 'init-tts-error':
        log('init-tts-error: %s', msg.error)
        this.initCallbacks['tts']?.reject(new Error(msg.error as string))
        delete this.initCallbacks['tts']
        break
      case 'transcribe-done':
      case 'transcribe-error':
      case 'synthesise-done':
      case 'synthesise-error': {
        const id = msg.id as string
        const p = this.pending.get(id)
        if (!p) {
          log('%s received for id=%s but no pending handler (cancelled?)', msg.type, id)
          break
        }
        this.pending.delete(id)
        if ((msg.type as string).endsWith('-error')) {
          log('%s id=%s: %s', msg.type, id, msg.error)
          p.reject(new Error(msg.error as string))
        } else {
          log('%s id=%s', msg.type, id)
          p.resolve(msg)
        }
        break
      }
    }
  }

  async initSTT(): Promise<SttInitResult> {
    log('initSTT()')
    const w = this.getWorker()
    return new Promise((resolve, reject) => {
      this.initCallbacks['stt'] = { resolve: resolve as (v: unknown) => void, reject }
      w.postMessage({ type: 'init-stt' })
    })
  }

  async initTTS(): Promise<TtsInitResult> {
    log('initTTS()')
    const w = this.getWorker()
    return new Promise((resolve, reject) => {
      this.initCallbacks['tts'] = { resolve: resolve as (v: unknown) => void, reject }
      w.postMessage({ type: 'init-tts' })
    })
  }

  async transcribe(audio: Float32Array, language?: string): Promise<{ text: string; language: string }> {
    const w = this.getWorker()
    const id = String(this.nextId++)
    log('transcribe request id=%s, audioLen=%d', id, audio.length)
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve: resolve as (v: unknown) => void, reject })
      w.postMessage({ type: 'transcribe', id, audio, language }, { transfer: [audio.buffer] })
    })
  }

  async synthesise(text: string, voiceId: string): Promise<Float32Array> {
    const w = this.getWorker()
    const id = String(this.nextId++)
    log('synthesise request id=%s, text="%s", voice=%s', id, text.slice(0, 40), voiceId)
    return new Promise((resolve, reject) => {
      this.pending.set(id, {
        resolve: (msg) => resolve((msg as { audio: Float32Array }).audio),
        reject,
      })
      w.postMessage({ type: 'synthesise', id, text, voiceId })
    })
  }

  cancel(id: string): void {
    const p = this.pending.get(id)
    if (p) {
      log('cancel id=%s', id)
      this.pending.delete(id)
      p.reject(new Error('Cancelled'))
    }
  }

  cancelAll(): void {
    if (this.pending.size === 0) return
    log('cancelAll (%d pending)', this.pending.size)
    for (const [id, p] of this.pending) {
      p.reject(new Error('Cancelled'))
      this.pending.delete(id)
    }
  }

  dispose(): void {
    log('dispose')
    this.cancelAll()
    this.worker?.terminate()
    this.worker = null
  }
}

export const voiceWorker = new VoiceWorkerClient()
```

- [ ] **Step 2: Type-check**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc -b`
Expected: TS errors in `whisperEngine.ts`, `kokoroEngine.ts`, `engineLoaderStore.ts` — caller signature mismatch. Fixed in Task 8.

- [ ] **Step 3: Commit**

```bash
cd /home/chris/workspace/chatsune && git add frontend/src/features/voice/workers/voiceWorkerClient.ts
git commit -m "Drop device param from voice worker client, plumb resolved back"
```

---

## Task 8: Update `whisperEngine.ts` and `kokoroEngine.ts` — drop device param

**Files:**
- Modify: `frontend/src/features/voice/engines/whisperEngine.ts`
- Modify: `frontend/src/features/voice/engines/kokoroEngine.ts`

- [ ] **Step 1: Replace `init` in `whisperEngine.ts`**

Replace the `init` method:

```ts
  async init(): Promise<void> {
    const { resolved } = await voiceWorker.initSTT()
    console.log('[voice] stt ready: %s/%s (fromCache=%s)', resolved.device, resolved.dtype, resolved.fromCache)
    await modelManager.markDownloaded('whisper-tiny')
    this.ready = true
  }
```

- [ ] **Step 2: Replace `init` in `kokoroEngine.ts`**

Read the file first to preserve the rest:

```bash
cat /home/chris/workspace/chatsune/frontend/src/features/voice/engines/kokoroEngine.ts
```

Then replace only the `init` method body + signature. The new `init` is:

```ts
  async init(): Promise<void> {
    const { voices, resolved } = await voiceWorker.initTTS()
    console.log('[voice] tts ready: %s/%s (fromCache=%s)', resolved.device, resolved.dtype, resolved.fromCache)
    this.voices = voices
    await modelManager.markDownloaded('kokoro-tts')
    this.ready = true
  }
```

(Keep the rest of the class — `synthesise`, `dispose`, `isReady`, `getVoices` etc. — unchanged.)

- [ ] **Step 3: Type-check**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc -b`
Expected: TS errors remaining only in `engineLoaderStore.ts` (passes `device` to `init()`). Fixed in Task 9.

- [ ] **Step 4: Commit**

```bash
cd /home/chris/workspace/chatsune && \
  git add frontend/src/features/voice/engines/whisperEngine.ts \
          frontend/src/features/voice/engines/kokoroEngine.ts
git commit -m "Drop device param from whisper and kokoro engine init"
```

---

## Task 9: Update `engineLoaderStore.ts` — stop detecting device manually

**Files:**
- Modify: `frontend/src/features/voice/stores/engineLoaderStore.ts`

- [ ] **Step 1: Remove `modelManager.detectDevice()` and the log line; call `init()` with no args**

In `frontend/src/features/voice/stores/engineLoaderStore.ts`, inside the `run()` function:

Replace:

```ts
    async function run() {
      const device = await modelManager.detectDevice()
      console.log(`[Voice Setup] Using device: ${device}`)
```

with:

```ts
    async function run() {
```

Replace:

```ts
        await whisperEngine.init(device)
```

with:

```ts
        await whisperEngine.init()
```

Replace:

```ts
        await kokoroEngine.init(device)
```

with:

```ts
        await kokoroEngine.init()
```

- [ ] **Step 2: Type-check**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc -b`
Expected: no errors

- [ ] **Step 3: Full build**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm run build`
Expected: build succeeds

- [ ] **Step 4: Full voice test suite**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm vitest run src/features/voice/`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
cd /home/chris/workspace/chatsune && git add frontend/src/features/voice/stores/engineLoaderStore.ts
git commit -m "Stop picking voice device in loader — worker decides"
```

---

## Task 10: Clean `useVoiceCapabilities.ts` — remove the now-unused `device` output

**Files:**
- Modify: `frontend/src/features/voice/hooks/useVoiceCapabilities.ts`

The worker now decides the device itself. The hook still exists for UI gating (`supported`, `sttSupported`) but the `device` field is dead.

Known consumer: `frontend/src/features/voice/components/VoiceSettings.tsx` destructures `device` and displays a "Runtime" panel. Previously `device` came from `detectDevice(caps)` which was just `caps.webgpu ? 'webgpu' : caps.wasm ? 'wasm' : null` — a capability-level approximation, not the actually-loaded dtype. Keep the same display semantics by computing it locally in the component.

- [ ] **Step 1: Update `VoiceSettings.tsx`**

Replace the destructure and the Runtime panel body:

```tsx
  const { settings, update } = useVoiceSettings()
  const { caps, supported, sttSupported } = useVoiceCapabilities()
  const device: 'webgpu' | 'wasm' | null = caps.webgpu ? 'webgpu' : caps.wasm ? 'wasm' : null
```

Leave the rest of the component unchanged. The existing `device === 'webgpu'` / `device === 'wasm'` branches keep working.

- [ ] **Step 2: Rewrite the hook**

Replace the hook's returned shape to drop `device`. New content:

```ts
import { useEffect, useState } from 'react'
import type { VoiceCapabilities } from '../types'

async function detectVoiceCapabilities(): Promise<VoiceCapabilities> {
  const caps: VoiceCapabilities = {
    getUserMedia: typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia,
    webgpu: false,
    wasm: typeof WebAssembly !== 'undefined' && typeof WebAssembly.validate === 'function',
    cacheStorage: typeof caches !== 'undefined',
  }

  if (typeof navigator !== 'undefined' && 'gpu' in navigator) {
    try {
      const adapter = await navigator.gpu.requestAdapter()
      caps.webgpu = adapter !== null
    } catch {
      // WebGPU API present but no adapter
    }
  }

  return caps
}

export function useVoiceCapabilities() {
  const [result, setResult] = useState<{
    caps: VoiceCapabilities
    supported: boolean
    sttSupported: boolean
  }>({
    caps: { getUserMedia: false, webgpu: false, wasm: false, cacheStorage: false },
    supported: false,
    sttSupported: false,
  })

  useEffect(() => {
    detectVoiceCapabilities().then((caps) => {
      const supported = (caps.webgpu || caps.wasm) && caps.cacheStorage
      const sttSupported = supported && caps.getUserMedia
      setResult({ caps, supported, sttSupported })
    })
  }, [])

  return result
}
```

- [ ] **Step 3: Type-check + full build**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm tsc -b && pnpm run build`
Expected: no errors, build succeeds

- [ ] **Step 4: Commit**

```bash
cd /home/chris/workspace/chatsune && \
  git add frontend/src/features/voice/hooks/useVoiceCapabilities.ts \
          frontend/src/features/voice/components/VoiceSettings.tsx
git commit -m "Remove device field from useVoiceCapabilities — worker decides"
```

---

## Task 11: Manual browser verification

No code changes — this is the integration sign-off.

- [ ] **Step 1: Start dev server**

Run: `cd /home/chris/workspace/chatsune/frontend && pnpm dev`

- [ ] **Step 2: Clear browser state**

In DevTools → Application → Storage → "Clear site data" (wipes CacheStorage + IndexedDB so we start fresh).

- [ ] **Step 3: Load the app, open DevTools console, activate voice**

Expected worker-log shape (shaderF16 may be true or false depending on hardware):

```
[VoiceWorker] whisper: capabilities=… fingerprint=webgpu/…/f16:false/v1
[VoiceWorker] whisper: cache MISS, walking ladder
[VoiceWorker] whisper: try webgpu/fp32
[VoiceWorker] whisper:   webgpu/fp32 — OK
[VoiceWorker] whisper: LOADED device=webgpu dtype=fp32 (fromCache=false)
[VoiceClient] init-stt-done: { device: 'webgpu', dtype: 'fp32', fromCache: false }
[voice] stt ready: webgpu/fp32 (fromCache=false)
```

- [ ] **Step 4: Reload the tab — verify cache HIT**

On the second load, expect compressed log:

```
[VoiceWorker] whisper: cache HIT → webgpu/fp32, loading...
[VoiceWorker] whisper: LOADED device=webgpu dtype=fp32 (fromCache=true)
```

- [ ] **Step 5: Run an STT request and a TTS request**

Use voice input in the app. Verify no errors in the console; Whisper returns a transcription and Kokoro plays audio.

- [ ] **Step 6: Inspect IndexedDB**

DevTools → Application → IndexedDB → `chatsune-voice-meta` → `dtypeDecisions`. Confirm entries exist for both `whisper:…` and `kokoro:…` keys.

- [ ] **Step 7: Capture a screenshot of the console log for PR description**

(Optional but useful.) The full ladder trace goes into the merge commit/PR description for future reference.

- [ ] **Step 8: Merge to master** (per project rule in `CLAUDE.md`)

If running on a feature branch:

```bash
cd /home/chris/workspace/chatsune && git checkout master && git merge --ff-only <branch> && git push
```

If already on master and committing incrementally, this step is a no-op.

---

## Self-Review Notes

- Spec §1 Capability Probe — covered in Task 3
- Spec §2 Ladder Definition — covered in Task 2
- Spec §3 Probe Mechanics & Failure Detection — covered in Task 5 (generic runner) + Task 6 (worker wiring with `env.webgpu.device`)
- Spec §4 Decision Cache (IndexedDB) — covered in Task 4
- Spec §5 Worker Interface Changes — covered in Tasks 6, 7, 8, 9
- Spec §6 File Layout — matches the File Structure section above
- Spec §7 Browser Logging — covered in Task 6 (worker-side `[VoiceWorker]` prefix) + Task 8 (`[voice] stt ready` line on client)
- Spec §8 Error Surface — Task 6 returns an `init-*-error` with the stringified attempts; the engine layer surfaces this as a thrown Error and the existing `engineLoaderStore` sets step status to `error` with the message
- Spec §9 Testing — Tasks 2, 3, 4, 5 cover all listed unit suites
