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
