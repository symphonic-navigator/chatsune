import type { STTEngine, TTSEngine, EngineRegistry } from '../types'

class EngineRegistryImpl<T extends STTEngine | TTSEngine> implements EngineRegistry<T> {
  private engines = new Map<string, T>()
  private activeEngine: T | undefined = undefined

  register(engine: T): void {
    this.engines.set(engine.id, engine)
    // Auto-promote the first registered engine so active() is never
    // undefined when at least one engine exists.
    if (!this.activeEngine) {
      this.activeEngine = engine
    }
  }

  get(id: string): T | undefined { return this.engines.get(id) }
  list(): T[] { return Array.from(this.engines.values()) }
  active(): T | undefined { return this.activeEngine }

  clearActive(): void { this.activeEngine = undefined }

  async setActive(id: string): Promise<void> {
    const engine = this.engines.get(id)
    if (!engine) throw new Error(`Engine "${id}" not registered`)
    if (this.activeEngine && this.activeEngine.id !== id) await this.activeEngine.dispose()
    this.activeEngine = engine
  }
}

export const sttRegistry = new EngineRegistryImpl<STTEngine>()
export const ttsRegistry = new EngineRegistryImpl<TTSEngine>()
