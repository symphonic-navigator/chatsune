type MicActivityListener = () => void

class MicActivityImpl {
  private level = 0
  private vadActive = false
  private listeners = new Set<MicActivityListener>()

  /** Hot path: called per frame from audioCapture's volume meter. */
  setLevel(value: number): void {
    this.level = value
    this.notify()
  }

  /** Edge-trigger only: notify on actual transitions. */
  setVadActive(value: boolean): void {
    if (this.vadActive === value) return
    this.vadActive = value
    this.notify()
  }

  getLevel(): number { return this.level }
  getVadActive(): boolean { return this.vadActive }

  subscribe(listener: MicActivityListener): () => void {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }

  private notify(): void {
    for (const l of this.listeners) {
      try { l() } catch (err) {
        console.error('[micActivity] Listener threw:', err)
      }
    }
  }
}

export const micActivity = new MicActivityImpl()
