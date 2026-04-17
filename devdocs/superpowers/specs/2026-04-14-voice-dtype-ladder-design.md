# Voice Dtype Ladder — Capability-Aware Fallback for Whisper & Kokoro

**Status:** Draft
**Date:** 2026-04-14
**Scope:** Frontend — `frontend/src/features/voice/`

## Problem

The voice feature runs Whisper (STT) and Kokoro (TTS) in-browser via
`@huggingface/transformers` and `kokoro-js`, on top of `onnxruntime-web`.
The right ONNX dtype to load depends on what the user's browser + GPU
actually support:

- `q8` / `int8` has no WebGPU kernel → silently falls back to WASM
- `fp16` and `q4f16` require the WebGPU `shader-f16` adapter feature →
  without it, session creation emits
  `Invalid ComputePipeline "Add"`-style validation errors
- `fp32` is universally safe but the largest download and not always
  the fastest option
- WASM has no fp16 compute speedup; its strong point is multi-threaded
  int8 (`q8`)

Today the worker hard-codes a single dtype per device, which is wrong for
users whose GPU lacks `shader-f16` (common) and wastes capability headroom
for users whose GPU has it. The system must pick the best dtype the
hardware can actually run.

## Goals

- Automatic, per-model dtype selection driven by probed WebGPU capabilities
- Separate preference ladders for Whisper (quality-sensitive) and Kokoro
- Ladders are **declarative** and editable without touching worker logic
- Decision is cached across sessions keyed by hardware fingerprint
- Deterministic failure detection: exceptions + WebGPU validation errors
  only — no timing heuristics

## Non-Goals (YAGNI)

- User-facing "force dtype" setting
- Active eviction of failed-dtype weights from browser CacheStorage /
  IndexedDB (disk is cheap; keep downloads for potential re-use)
- Per-op CPU-fallback detection beyond what the browser surfaces as errors

## Design

### 1. Capability Probe & Fingerprint

On first worker init, run once and memoise for the worker's lifetime:

```ts
interface VoiceCapabilities {
  webgpu: boolean
  shaderF16: boolean
  adapterInfo: { vendor: string; architecture: string } | null
}
```

Fingerprint used as IndexedDB key component:

- WebGPU path: `webgpu/${vendor}/${architecture}/f16:${bool}/v${CACHE_VERSION}`
- WASM only:  `wasm/v${CACHE_VERSION}`

`CACHE_VERSION` is a constant bumped manually when ladders or the relevant
libraries (`@huggingface/transformers`, `kokoro-js`, `onnxruntime-web`) are
updated. This is the invalidation mechanism — no heuristic needed.

### 2. Ladder Definition

Lives in `frontend/src/features/voice/infrastructure/dtypeLadder.ts`.
Ladders are ordered best-to-worst; the first entry that loads and warms
up without errors wins. Entries tagged `requires: 'shader-f16'` are
filtered out at runtime if the capability is missing.

```ts
type DtypeEntry =
  | { device: 'webgpu'; dtype: 'q4f16' | 'fp16'; requires: 'shader-f16' }
  | { device: 'webgpu'; dtype: 'q4' | 'fp32' }
  | { device: 'wasm'; dtype: 'q8' | 'q4' | 'fp32' }

// Whisper: quality over size on GPU — prefer fp16 first.
export const WHISPER_LADDER: DtypeEntry[] = [
  { device: 'webgpu', dtype: 'fp16',  requires: 'shader-f16' },
  { device: 'webgpu', dtype: 'q4f16', requires: 'shader-f16' },
  { device: 'webgpu', dtype: 'fp32' },
  { device: 'webgpu', dtype: 'q4' },
  { device: 'wasm',   dtype: 'q8' },
  { device: 'wasm',   dtype: 'fp32' },
]

// Kokoro: speech synthesis tolerates quantisation better than
// transcription — prefer small quants first.
export const KOKORO_LADDER: DtypeEntry[] = [
  { device: 'webgpu', dtype: 'q4f16', requires: 'shader-f16' },
  { device: 'webgpu', dtype: 'fp16',  requires: 'shader-f16' },
  { device: 'webgpu', dtype: 'q4' },
  { device: 'webgpu', dtype: 'fp32' },
  { device: 'wasm',   dtype: 'q8' },
  { device: 'wasm',   dtype: 'fp32' },
]
```

### 3. Probe Mechanics & Failure Detection

Per ladder step, the runner performs:

1. If `device === 'webgpu'`: attach uncaptured-error listener to the
   shared ORT WebGPU device (accessed via `env.webgpu.device` from
   `@huggingface/transformers`). Errors pushed into a local array.
2. Call the model-specific load function:
   - Whisper: `pipeline('automatic-speech-recognition', ...)`
   - Kokoro:  `KokoroTTS.from_pretrained(...)`
   A thrown exception → fail this step.
3. Warmup inference:
   - STT: transcribe a 1-second silent `Float32Array`
   - TTS: synthesise the short literal `"test"`
   A thrown exception → fail this step.
4. Yield one microtask, then inspect the collected WebGPU errors.
   Non-empty → fail this step.
5. Detach listener. Step succeeded; keep the loaded model, return the
   `{ device, dtype }` tuple.

Failure at any sub-step advances to the next ladder entry. No weight
eviction between attempts.

### 4. Decision Cache (IndexedDB)

Database: `chatsune-voice-meta`, object store: `dtypeDecisions`.

```ts
type DecisionKey = `${modelId}:${fingerprint}`
interface Decision {
  device: 'webgpu' | 'wasm'
  dtype: string
  decidedAt: string // ISO
  cacheVersion: number
}
```

Per model-init flow:

```
1. caps = probeCapabilities() (memoised)
2. fp = computeFingerprint(caps)
3. cached = await dtypeCache.get(modelId, fp)
4. if cached:
     try loadAndWarmup(cached)
     success → emit init-done (fromCache: true); return
     failure → fall through
5. ladder = filterLadder(modelLadder, caps)
6. for entry in ladder:
     try loadAndWarmup(entry)
     success → dtypeCache.set(...); emit init-done; return
7. emit init-error (recoverable: false)
```

### 5. Worker Interface Changes

The client no longer picks a device. Device and dtype are the worker's
concern.

**Before:**

```ts
{ type: 'init-stt', device: 'webgpu' | 'wasm' | 'cpu' }
```

**After:**

```ts
{ type: 'init-stt' }

// response:
{
  type: 'init-stt-done',
  resolved: { device: 'webgpu', dtype: 'fp16', fromCache: true }
}
```

`useVoiceCapabilities` continues to expose `supported` / `sttSupported`
for UI gating, but the device field is removed from its output.

### 6. File Layout

New:

```
frontend/src/features/voice/infrastructure/
  dtypeLadder.ts       # ladder constants, DtypeEntry type
  capabilityProbe.ts   # probeCapabilities(), computeFingerprint(),
                       # CACHE_VERSION constant
  dtypeCache.ts        # IndexedDB wrapper, Decision type

frontend/src/features/voice/workers/
  voiceLadderRunner.ts # walkLadder<T>(...) — generic step runner
                       # with error-listener lifecycle and warmup
```

Modified:

```
frontend/src/features/voice/workers/voiceWorker.ts
  - drop msg.device param from init-stt / init-tts
  - delegate dtype selection to walkLadder
  - emit resolved { device, dtype, fromCache } in init-done

frontend/src/features/voice/workers/voiceWorkerClient.ts
  - stop passing device in postMessage init-stt / init-tts
  - plumb resolved back to callers (for logging/UI)

frontend/src/features/voice/hooks/useVoiceCapabilities.ts
  - remove device field from return value (keep supported flags)
```

### 7. Browser Logging

Every ladder decision is visible in the browser console so the developer
can verify which path the worker actually took.

Worker-side (`[VoiceWorker]` prefix):

```
[VoiceWorker] whisper: capabilities {webgpu: true, shaderF16: false, ...}
[VoiceWorker] whisper: fingerprint=wasm/v1
[VoiceWorker] whisper: cache MISS, walking ladder
[VoiceWorker] whisper: try webgpu/fp16 — SKIPPED (requires shader-f16)
[VoiceWorker] whisper: try webgpu/fp32 — FAILED (GPUValidationError: ...)
[VoiceWorker] whisper: try webgpu/q4 — OK, warmup 820 ms
[VoiceWorker] whisper: LOADED device=webgpu dtype=q4 (fromCache=false)
```

On cache hits the ladder walk is compressed to a single line:

```
[VoiceWorker] kokoro: cache HIT → webgpu/q4f16, loading...
[VoiceWorker] kokoro: LOADED device=webgpu dtype=q4f16 (fromCache=true)
```

Client-side receives the resolved tuple in `init-*-done` and logs it once
at INFO level with the same shape (`[voice] stt ready: webgpu/q4`), so
the decision is visible without opening the worker console.

### 8. Error Surface

If every ladder entry fails (including both WASM fallbacks), the worker
emits an ErrorEvent on its init channel with:

- `recoverable: false`
- `user_message: "Voice can't be started on this device"`
- `detail`: list of attempted `(device, dtype, reason)` triples for the
  dev console / logs

### 9. Testing

Vitest unit coverage:

- `dtypeLadder.ts` — `filterLadder()` strips `requires:'shader-f16'`
  entries correctly for every capability combination; strips all
  `webgpu` entries when `!caps.webgpu`
- `capabilityProbe.ts` — mocked `navigator.gpu`; fingerprint shape
  stable across equal inputs, changes on any capability flip
- `dtypeCache.ts` — round-trip with `fake-indexeddb`; `cacheVersion`
  mismatch treated as miss
- `voiceLadderRunner.ts` — `walkLadder` with fake `loadFn` signatures;
  injected GPU errors cause step failure; early exception in warmup
  advances the ladder

Worker itself remains untested (integration layer; verified manually
in browser).

## Migration / Rollout

Single-shot change. The stopgap fp32-everywhere in `voiceWorker.ts`
stays until the ladder lands; the same commit that adds the ladder
removes the stopgap. No flag, no gradual rollout — voice is a local
client feature with no backend dependency.

## Open Questions

None at design-approval time.

## Future Work (explicitly out of scope)

- Settings UI to force a specific `(device, dtype)` per model
- Active CacheStorage / IndexedDB eviction of failed weights
- Telemetry on ladder outcomes to tune defaults across the user base
