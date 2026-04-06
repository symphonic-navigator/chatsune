import { useEffect } from "react"
import { useNotificationStore } from "../../../core/store/notificationStore"
import { Toast } from "./Toast"

const MAX_VISIBLE = 3

export function ToastContainer() {
  const notifications = useNotificationStore((s) => s.notifications)
  const dismissToast = useNotificationStore((s) => s.dismissToast)

  const visible = notifications.filter((n) => !n.dismissed)

  // Auto-dismiss notifications beyond MAX_VISIBLE
  useEffect(() => {
    visible.slice(MAX_VISIBLE).forEach((n) => dismissToast(n.id))
  }, [visible, dismissToast])

  const displayed = visible.slice(0, MAX_VISIBLE)

  if (displayed.length === 0) return null

  return (
    <div className="pointer-events-none fixed top-14 left-1/2 z-50 flex -translate-x-1/2 flex-col gap-3 p-4">
      {displayed.map((n) => (
        <Toast key={n.id} notification={n} />
      ))}
    </div>
  )
}
