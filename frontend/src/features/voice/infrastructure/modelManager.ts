import type { ModelInfo } from '../types'

const CACHE_NAME = 'chatsune-voice-models'

const MODEL_URLS: Record<string, { url: string; label: string; size: number }> = {
  'whisper-tiny': { url: 'onnx-community/whisper-tiny', label: 'Speech Recognition', size: 31_000_000 },
  'silero-vad': { url: '@ricky0123/vad-web', label: 'Voice Detection', size: 1_500_000 },
  'kokoro-tts': { url: 'onnx-community/Kokoro-82M-v1.0-ONNX', label: 'Speech Synthesis', size: 40_000_000 },
}

class ModelManagerImpl {
  private cache: Cache | null = null

  private async getCache(): Promise<Cache> {
    if (!this.cache) this.cache = await caches.open(CACHE_NAME)
    return this.cache
  }

  async isDownloaded(modelId: string): Promise<boolean> {
    const cache = await this.getCache()
    const response = await cache.match(modelId)
    return response !== null
  }

  async markDownloaded(modelId: string): Promise<void> {
    const cache = await this.getCache()
    await cache.put(modelId, new Response('ok'))
  }

  async delete(modelId: string): Promise<void> {
    const cache = await this.getCache()
    await cache.delete(modelId)
  }

  async getStorageUsage(): Promise<{ used: number; models: ModelInfo[] }> {
    const models: ModelInfo[] = []
    let used = 0
    for (const [id, meta] of Object.entries(MODEL_URLS)) {
      const downloaded = await this.isDownloaded(id)
      models.push({ id, label: meta.label, size: meta.size, downloaded })
      if (downloaded) used += meta.size
    }
    return { used, models }
  }

  getModelList(): ModelInfo[] {
    return Object.entries(MODEL_URLS).map(([id, meta]) => ({ id, label: meta.label, size: meta.size, downloaded: false }))
  }

  async detectDevice(): Promise<'webgpu' | 'wasm'> {
    if (typeof navigator !== 'undefined' && 'gpu' in navigator) {
      try {
        const adapter = await navigator.gpu.requestAdapter()
        if (adapter) return 'webgpu'
      } catch {
        // WebGPU API exists but no adapter available
      }
    }
    return 'wasm'
  }
}

export const modelManager = new ModelManagerImpl()
