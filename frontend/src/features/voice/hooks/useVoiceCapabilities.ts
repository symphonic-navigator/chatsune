import { useEffect, useState } from 'react'
import type { VoiceCapabilities, VoiceDevice } from '../types'

async function detectVoiceCapabilities(): Promise<VoiceCapabilities> {
  const caps: VoiceCapabilities = {
    getUserMedia: typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia,
    webgpu: false,
    wasm: typeof WebAssembly !== 'undefined' && typeof WebAssembly.validate === 'function',
    cacheStorage: typeof caches !== 'undefined',
  }

  // Actually probe for a WebGPU adapter — 'gpu' in navigator is not enough
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

function detectDevice(caps: VoiceCapabilities): VoiceDevice | null {
  if (caps.webgpu) return 'webgpu'
  if (caps.wasm) return 'wasm'
  return null
}

export function useVoiceCapabilities() {
  const [result, setResult] = useState<{
    caps: VoiceCapabilities
    device: VoiceDevice | null
    supported: boolean
    sttSupported: boolean
  }>({
    caps: { getUserMedia: false, webgpu: false, wasm: false, cacheStorage: false },
    device: null,
    supported: false,
    sttSupported: false,
  })

  useEffect(() => {
    detectVoiceCapabilities().then((caps) => {
      const device = detectDevice(caps)
      const supported = device !== null && caps.cacheStorage
      const sttSupported = supported && caps.getUserMedia
      setResult({ caps, device, supported, sttSupported })
    })
  }, [])

  return result
}
