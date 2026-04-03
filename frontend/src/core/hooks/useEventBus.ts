import { useEffect, useRef, useState } from "react"
import { eventBus } from "../websocket/eventBus"
import type { BaseEvent } from "../types/events"

export function useEventBus(eventType: string, maxHistory = 100) {
  const [events, setEvents] = useState<BaseEvent[]>([])
  const eventsRef = useRef<BaseEvent[]>([])

  useEffect(() => {
    eventsRef.current = []
    setEvents([])

    const unsubscribe = eventBus.on(eventType, (event) => {
      eventsRef.current = [...eventsRef.current.slice(-(maxHistory - 1)), event]
      setEvents(eventsRef.current)
    })

    return unsubscribe
  }, [eventType, maxHistory])

  const clear = () => {
    eventsRef.current = []
    setEvents([])
  }

  return { events, latest: events[events.length - 1] ?? null, clear }
}
