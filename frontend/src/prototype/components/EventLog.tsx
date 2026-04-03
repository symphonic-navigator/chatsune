import { useEffect, useRef, useState } from "react"
import { useEventBus } from "../../core/hooks/useEventBus"
import type { BaseEvent } from "../../core/types/events"

const categoryColours: Record<string, string> = {
  user: "text-blue-600 bg-blue-50",
  llm: "text-green-600 bg-green-50",
  persona: "text-purple-600 bg-purple-50",
  setting: "text-orange-600 bg-orange-50",
  audit: "text-gray-600 bg-gray-50",
  error: "text-red-600 bg-red-50",
}

function getCategoryColour(eventType: string): string {
  const prefix = eventType.split(".")[0]
  return categoryColours[prefix] ?? "text-gray-600 bg-gray-50"
}

function formatTimestamp(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString()
  } catch {
    return ts
  }
}

interface EventRowProps {
  event: BaseEvent
}

function EventRow({ event }: EventRowProps) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="border-b border-gray-100 px-3 py-2 text-sm">
      <div
        className="flex cursor-pointer items-center gap-3"
        onClick={() => setExpanded(!expanded)}
      >
        <span className="w-20 shrink-0 text-xs text-gray-400">
          {formatTimestamp(event.timestamp)}
        </span>
        <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${getCategoryColour(event.type)}`}>
          {event.type}
        </span>
        <span className="text-xs text-gray-400">{event.scope}</span>
        <span className="ml-auto text-xs text-gray-300">{expanded ? "▼" : "▶"}</span>
      </div>
      {expanded && (
        <div className="mt-2 ml-20">
          <div className="text-xs text-gray-400 mb-1">
            id: {event.id} | correlation: {event.correlation_id} | seq: {event.sequence}
          </div>
          <pre className="rounded bg-gray-50 p-2 text-xs text-gray-700 overflow-auto max-h-48">
            {JSON.stringify(event.payload, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}

interface EventLogProps {
  maxHeight?: string
  filter?: string
}

export default function EventLog({ maxHeight = "calc(100vh - 300px)", filter }: EventLogProps) {
  const { events, clear } = useEventBus(filter ?? "*", 500)
  const [paused, setPaused] = useState(false)
  const [typeFilter, setTypeFilter] = useState("")
  const containerRef = useRef<HTMLDivElement>(null)

  const displayedEvents = typeFilter
    ? events.filter((e) => e.type.includes(typeFilter))
    : events

  useEffect(() => {
    if (!paused && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [displayedEvents.length, paused])

  return (
    <div className="rounded-lg border border-gray-200 bg-white">
      <div className="flex items-center justify-between border-b border-gray-200 px-4 py-2">
        <h3 className="text-sm font-medium">Event Log</h3>
        <div className="flex items-center gap-2">
          <input
            type="text"
            placeholder="Filter by type..."
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            className="rounded border border-gray-200 px-2 py-1 text-xs focus:border-blue-500 focus:outline-none"
          />
          <span className="text-xs text-gray-400">{displayedEvents.length} events</span>
          <button
            onClick={() => setPaused(!paused)}
            className={`rounded px-2 py-1 text-xs ${paused ? "bg-amber-100 text-amber-700" : "bg-gray-100 text-gray-600"}`}
          >
            {paused ? "Paused" : "Pause"}
          </button>
          <button
            onClick={clear}
            className="rounded bg-gray-100 px-2 py-1 text-xs text-gray-600 hover:bg-gray-200"
          >
            Clear
          </button>
        </div>
      </div>
      <div ref={containerRef} className="overflow-auto" style={{ maxHeight }}>
        {displayedEvents.length === 0 ? (
          <p className="p-4 text-center text-sm text-gray-400">No events yet</p>
        ) : (
          displayedEvents.map((event) => <EventRow key={event.id} event={event} />)
        )}
      </div>
    </div>
  )
}
