import { useAuthStore } from "../../core/store/authStore"
import { useEventStore, type ConnectionStatus } from "../../core/store/eventStore"

const statusColours: Record<ConnectionStatus, string> = {
  connected: "bg-green-500",
  connecting: "bg-yellow-500",
  reconnecting: "bg-yellow-500",
  disconnected: "bg-red-500",
}

const statusLabels: Record<ConnectionStatus, string> = {
  connected: "Connected",
  connecting: "Connecting...",
  reconnecting: "Reconnecting...",
  disconnected: "Disconnected",
}

export default function StatusBar() {
  const status = useEventStore((s) => s.status)
  const user = useAuthStore((s) => s.user)

  return (
    <div className="flex items-center justify-between border-b border-gray-200 bg-white px-6 py-3">
      <div className="flex items-center gap-3">
        <span className={`inline-block h-2.5 w-2.5 rounded-full ${statusColours[status]}`} />
        <span className="text-sm text-gray-600">{statusLabels[status]}</span>
      </div>
      {user && (
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium">{user.display_name || user.username}</span>
          <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
            {user.role}
          </span>
        </div>
      )}
    </div>
  )
}
