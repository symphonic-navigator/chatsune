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

    // SwiftShader is Chromium's CPU-based software Vulkan implementation.
    // It satisfies the WebGPU API but every "GPU" op runs on the CPU, slower
    // than the multi-threaded WASM path. Treat it as unavailable so the
    // ladder falls through to wasm.
    if (adapter.info?.vendor === 'google' && adapter.info?.architecture === 'swiftshader') {
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
