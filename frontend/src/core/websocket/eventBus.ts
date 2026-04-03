import type { BaseEvent } from "../types/events"

type EventCallback = (event: BaseEvent) => void

class EventBus {
  private listeners = new Map<string, Set<EventCallback>>()

  on(eventType: string, callback: EventCallback): () => void {
    if (!this.listeners.has(eventType)) {
      this.listeners.set(eventType, new Set())
    }
    this.listeners.get(eventType)!.add(callback)

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

    // Notify prefix subscribers (e.g. "persona.*" matches "persona.created")
    const parts = event.type.split(".")
    if (parts.length > 1) {
      const prefix = parts[0] + ".*"
      this.listeners.get(prefix)?.forEach((cb) => cb(event))
    }
  }

  clear() {
    this.listeners.clear()
  }
}

export const eventBus = new EventBus()
