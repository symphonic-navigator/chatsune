import { useEffect, useState } from "react"
import { eventBus } from "../websocket/eventBus"
import type { BaseEvent } from "../types/events"

export function useEventBus(eventType: string, maxHistory = 100) {
  const [events, setEvents] = useState<BaseEvent[]>([])

  useEffect(() => {
    setEvents([])

    const unsubscribe = eventBus.on(eventType, (event) => {
      setEvents((prev) => [...prev.slice(-(maxHistory - 1)), event])
    })

    return unsubscribe
  }, [eventType, maxHistory])

  const clear = () => setEvents([])

  return { events, latest: events[events.length - 1] ?? null, clear }
}
