import { useNotificationStore } from "../../../core/store/notificationStore"
import { useViewport } from "../../../core/hooks/useViewport"
import { MobileToast } from "./MobileToast"

/**
 * Mobile-only toast renderer. Shows a single, solid, bottom-anchored toast.
 * New notifications replace the current one; there is no queue and no
 * stacking. The desktop renderer (`ToastContainer`) remains the source of
 * stacked, glassy toasts on `>= lg`.
 */
export function MobileToastContainer() {
  const { isMobile } = useViewport()
  const notifications = useNotificationStore((s) => s.notifications)

  if (!isMobile) return null

  const visible = notifications.filter((n) => !n.dismissed)
  if (visible.length === 0) return null

  // Store prepends new entries, so the first visible notification is the
  // most recent one.
  const top = visible[0]

  return (
    <div
      className="pointer-events-none fixed left-1/2 z-[60] flex -translate-x-1/2 justify-center"
      style={{
        bottom: "calc(env(safe-area-inset-bottom) + 1rem)",
      }}
    >
      <MobileToast key={top.id} notification={top} />
    </div>
  )
}
