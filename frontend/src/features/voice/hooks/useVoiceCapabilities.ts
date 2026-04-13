import { useMemo } from 'react'
import type { VoiceCapabilities, VoiceDevice } from '../types'

export function detectVoiceCapabilities(): VoiceCapabilities {
  return {
    getUserMedia: typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia,
    webgpu: typeof navigator !== 'undefined' && 'gpu' in navigator,
    wasm: typeof WebAssembly !== 'undefined' && typeof WebAssembly.validate === 'function',
    cacheStorage: typeof caches !== 'undefined',
  }
}

export function detectDevice(caps: VoiceCapabilities): VoiceDevice | null {
  if (caps.webgpu) return 'webgpu'
  if (caps.wasm) return 'wasm'
  return null
}

export function useVoiceCapabilities() {
  return useMemo(() => {
    const caps = detectVoiceCapabilities()
    const device = detectDevice(caps)
    const supported = device !== null && caps.cacheStorage
    const sttSupported = supported && caps.getUserMedia
    return { caps, device, supported, sttSupported }
  }, [])
}
