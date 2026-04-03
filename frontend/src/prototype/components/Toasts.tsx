import { useEffect, useRef } from "react"
import { useNotificationStore, type AppNotification } from "../../core/store/notificationStore"

const AUTO_DISMISS_MS = 5_000
const MAX_VISIBLE = 3

const levelStyles: Record<AppNotification["level"], string> = {
  success: "border-l-4 border-l-green-400 bg-green-50 text-green-800",
  error: "border-l-4 border-l-red-400 bg-red-50 text-red-800",
  info: "border-l-4 border-l-gray-400 bg-gray-50 text-gray-800",
}

export default function Toasts() {
  const notifications = useNotificationStore((s) => s.notifications)
  const dismissToast = useNotificationStore((s) => s.dismissToast)
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())

  const visible = notifications.filter((n) => !n.dismissed).slice(0, MAX_VISIBLE)

  useEffect(() => {
    for (const n of visible) {
      if (n.level === "error") continue
      if (timers.current.has(n.id)) continue
      const timer = setTimeout(() => {
        dismissToast(n.id)
        timers.current.delete(n.id)
      }, AUTO_DISMISS_MS)
      timers.current.set(n.id, timer)
    }

    return () => {
      for (const timer of timers.current.values()) clearTimeout(timer)
      timers.current.clear()
    }
  })

  if (visible.length === 0) return null

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 w-80">
      {visible.map((n) => (
        <div
          key={n.id}
          onClick={() => dismissToast(n.id)}
          className={`cursor-pointer rounded-lg px-4 py-3 shadow-md transition-opacity ${levelStyles[n.level]}`}
        >
          <p className="text-sm font-medium">{n.title}</p>
          {n.message && <p className="mt-0.5 text-xs opacity-80">{n.message}</p>}
        </div>
      ))}
    </div>
  )
}
