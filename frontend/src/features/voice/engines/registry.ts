import type { STTEngine, TTSEngine, EngineRegistry } from '../types'

class EngineRegistryImpl<T extends STTEngine | TTSEngine> implements EngineRegistry<T> {
  private engines = new Map<string, T>()

  register(engine: T): void {
    this.engines.set(engine.id, engine)
  }

  get(id: string): T | undefined { return this.engines.get(id) }
  list(): T[] { return Array.from(this.engines.values()) }
}

export const sttRegistry = new EngineRegistryImpl<STTEngine>()
export const ttsRegistry = new EngineRegistryImpl<TTSEngine>()

// Provider → engine id mapping. Plugins declare their pair at plugin-
// registration time. Used by the resolver helpers (Task 18) to pick the
// right engine for a persona's tts_provider_id or the user's stt_provider_id.
type EngineKind = 'stt' | 'tts'

const providerEngineMap = new Map<string, { stt?: string; tts?: string }>()

export function declareProviderEngines(
  integrationId: string,
  engines: { stt?: string; tts?: string },
): void {
  providerEngineMap.set(integrationId, engines)
}

export function providerToEngineId(
  integrationId: string,
  kind: EngineKind,
): string | undefined {
  return providerEngineMap.get(integrationId)?.[kind]
}
