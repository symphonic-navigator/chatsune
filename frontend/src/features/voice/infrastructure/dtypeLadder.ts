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
