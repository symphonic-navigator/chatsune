import { useCallback, useEffect, useRef, useState } from "react"
import type { AppNotification } from "../../../core/store/notificationStore"
import { useNotificationStore } from "../../../core/store/notificationStore"

const LEVEL_COLOURS: Record<AppNotification["level"], string> = {
  success: "34,197,94",   // --color-live
  info: "124,92,191",     // --color-purple
  warning: "201,168,76",  // --color-gold
  error: "248,113,113",   // red-400
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

interface ToastProps {
  notification: AppNotification
}

export function Toast({ notification }: ToastProps) {
  const dismissToast = useNotificationStore((s) => s.dismissToast)
  const [exiting, setExiting] = useState(false)

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const remainingRef = useRef<number | null>(null)
  const startedAtRef = useRef<number>(0)

  const duration = notification.duration ?? DEFAULT_DURATIONS[notification.level]

  const dismiss = useCallback(() => {
    setExiting(true)
    setTimeout(() => dismissToast(notification.id), 200)
  }, [dismissToast, notification.id])

  const startTimer = useCallback(
    (ms: number) => {
      remainingRef.current = ms
      startedAtRef.current = Date.now()
      timerRef.current = setTimeout(dismiss, ms)
    },
    [dismiss],
  )

  const pauseTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current)
      timerRef.current = null
      const elapsed = Date.now() - startedAtRef.current
      remainingRef.current = Math.max((remainingRef.current ?? 0) - elapsed, 0)
    }
  }, [])

  const resumeTimer = useCallback(() => {
    if (remainingRef.current !== null && remainingRef.current > 0) {
      startTimer(remainingRef.current)
    }
  }, [startTimer])

  useEffect(() => {
    // duration === null is the existing "no auto-dismiss" sentinel from
    // DEFAULT_DURATIONS lookups. duration <= 0 is the new sticky-toast
    // sentinel for callers that explicitly want a non-dismissing toast
    // (e.g. "new version available" with an action button).
    if (duration !== null && duration > 0) {
      startTimer(duration)
    }
    return () => {
      if (timerRef.current !== null) clearTimeout(timerRef.current)
    }
  }, [duration, startTimer])

  const rgb = LEVEL_COLOURS[notification.level]
  const icon = LEVEL_ICONS[notification.level]

  const handleAction = () => {
    notification.action?.onClick()
    dismiss()
  }

  return (
    <div
      className={`pointer-events-auto flex max-w-md items-center gap-3 rounded-lg px-4 py-3 shadow-lg lg:backdrop-blur-sm ${exiting ? "animate-toast-exit" : "animate-toast-enter"}`}
      style={{
        background: `rgba(${rgb}, 0.08)`,
        border: `1px solid rgba(${rgb}, 0.25)`,
      }}
      onMouseEnter={pauseTimer}
      onMouseLeave={resumeTimer}
    >
      <span
        className="flex-shrink-0 text-lg"
        style={{ color: `rgb(${rgb})` }}
      >
        {icon}
      </span>

      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-semibold text-white/90">
          {notification.title}
        </div>
        {notification.message && (
          <div className="mt-0.5 text-[11px] text-white/50">
            {notification.message}
          </div>
        )}
      </div>

      {notification.action && (
        <button
          className="flex-shrink-0 cursor-pointer rounded-md px-2.5 py-1 text-[11px] transition-colors"
          style={{
            color: `rgb(${rgb})`,
            background: `rgba(${rgb}, 0.15)`,
            border: `1px solid rgba(${rgb}, 0.3)`,
          }}
          onClick={handleAction}
        >
          {notification.action.label}
        </button>
      )}

      <button
        className="flex-shrink-0 cursor-pointer text-sm text-white/30 transition-colors hover:text-white/60"
        onClick={dismiss}
      >
        {"\u00D7"}
      </button>
    </div>
  )
}
