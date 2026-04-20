import { useCallback, useEffect, useRef, useState } from "react"
import type { AppNotification } from "../../../core/store/notificationStore"
import { useNotificationStore } from "../../../core/store/notificationStore"

const LEVEL_COLOURS: Record<AppNotification["level"], string> = {
  success: "34,197,94",
  info: "124,92,191",
  warning: "201,168,76",
  error: "248,113,113",
}

const LEVEL_ICONS: Record<AppNotification["level"], string> = {
  success: "\u2713",
  info: "\u2139",
  warning: "\u26A0",
  error: "\u2717",
}

const DEFAULT_DURATIONS: Record<AppNotification["level"], number | null> = {
  success: 4000,
  info: 4000,
  warning: 6000,
  error: 10000,
}

const SWIPE_DISMISS_THRESHOLD_PX = 40
const EXIT_ANIMATION_MS = 200

interface MobileToastProps {
  notification: AppNotification
}

export function MobileToast({ notification }: MobileToastProps) {
  const dismissToast = useNotificationStore((s) => s.dismissToast)
  const [exiting, setExiting] = useState(false)
  const [dragY, setDragY] = useState(0)
  const pointerStartY = useRef<number | null>(null)
  const pointerMoved = useRef(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const rgb = LEVEL_COLOURS[notification.level]
  const icon = LEVEL_ICONS[notification.level]
  const duration = notification.duration ?? DEFAULT_DURATIONS[notification.level]

  const didDismissRef = useRef(false)

  const dismiss = useCallback(() => {
    if (didDismissRef.current) return
    didDismissRef.current = true
    setExiting(true)
    setTimeout(() => dismissToast(notification.id), EXIT_ANIMATION_MS)
  }, [dismissToast, notification.id])

  useEffect(() => {
    if (duration === null) return
    timerRef.current = setTimeout(dismiss, duration)
    return () => {
      if (timerRef.current !== null) clearTimeout(timerRef.current)
    }
  }, [dismiss, duration])

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    pointerStartY.current = e.clientY
    pointerMoved.current = false
    ;(e.currentTarget as HTMLDivElement).setPointerCapture?.(e.pointerId)
  }

  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (pointerStartY.current === null) return
    const dy = e.clientY - pointerStartY.current
    if (Math.abs(dy) > 2) pointerMoved.current = true
    setDragY(Math.max(0, dy))
  }

  const onPointerUp = () => {
    if (pointerStartY.current !== null && dragY >= SWIPE_DISMISS_THRESHOLD_PX) {
      dismiss()
    }
    pointerStartY.current = null
    setDragY(0)
  }

  const onPointerCancel = () => {
    pointerStartY.current = null
    setDragY(0)
  }

  const onClick = () => {
    if (!pointerMoved.current) dismiss()
  }

  return (
    <div
      role="status"
      aria-live="polite"
      className={`pointer-events-auto flex w-[calc(100vw-2rem)] max-w-md items-start gap-3 rounded-xl px-4 py-3 shadow-2xl transition-transform ${exiting ? "animate-toast-exit" : "animate-toast-enter"}`}
      style={{
        background: "#0b0a08",
        borderTop: `1px solid rgba(${rgb}, 0.35)`,
        borderRight: `1px solid rgba(${rgb}, 0.35)`,
        borderBottom: `1px solid rgba(${rgb}, 0.35)`,
        borderLeft: `4px solid rgb(${rgb})`,
        transform: dragY > 0 ? `translateY(${dragY}px)` : undefined,
        opacity: dragY > 0 ? Math.max(0.3, 1 - dragY / 200) : 1,
      }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerCancel}
      onClick={onClick}
    >
      <span
        className="flex-shrink-0 pt-0.5 text-lg"
        style={{ color: `rgb(${rgb})` }}
      >
        {icon}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[14px] font-semibold text-white/95">
          {notification.title}
        </div>
        {notification.message && (
          <div className="mt-0.5 text-[12px] text-white/70">
            {notification.message}
          </div>
        )}
      </div>
    </div>
  )
}
