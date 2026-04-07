import type { BaseEvent } from "../types/events"

type EventCallback = (event: BaseEvent) => void

class EventBus {
  private listeners = new Map<string, Set<EventCallback>>()

  on(eventType: string, callback: EventCallback): () => void {
    if (!this.listeners.has(eventType)) {
      this.listeners.set(eventType, new Set())
    }
    const set = this.listeners.get(eventType)!
    set.add(callback)

    // Dev-only leak guard: surfaces hooks that fail to unsubscribe on unmount.
    if (import.meta.env.DEV && set.size > 100) {
      console.warn(
        `[eventBus] Listener count for "${eventType}" exceeded 100 (now ${set.size}). Possible leak — check unsubscribe in hook cleanup.`,
      )
    }

    return () => {
      this.listeners.get(eventType)?.delete(callback)
    }
  }

  emit(event: BaseEvent) {
    // Notify exact type subscribers
    this.listeners.get(event.type)?.forEach((cb) => cb(event))

    // Notify wildcard subscribers
    if (event.type !== "*") {
      this.listeners.get("*")?.forEach((cb) => cb(event))
    }

    // Notify prefix subscribers recursively (e.g. "persona.*" matches "persona.memory.created",
    // "persona.memory.*" matches "persona.memory.created", etc.)
    const parts = event.type.split(".")
    for (let i = 1; i < parts.length; i++) {
      const prefix = parts.slice(0, i).join(".") + ".*"
      this.listeners.get(prefix)?.forEach((cb) => cb(event))
    }
  }

  clear() {
    this.listeners.clear()
  }
}

export const eventBus = new EventBus()
