import { useAuthStore } from "../../core/store/authStore"
import { useEventStore } from "../../core/store/eventStore"
import EventLog from "../components/EventLog"

export default function DashboardPage() {
  const user = useAuthStore((s) => s.user)
  const status = useEventStore((s) => s.status)
  const lastSequence = useEventStore((s) => s.lastSequence)

  return (
    <div className="space-y-6">
      <h2 className="text-lg font-semibold">Dashboard</h2>

      <div className="grid grid-cols-3 gap-4">
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <p className="text-sm text-gray-500">User</p>
          <p className="text-lg font-medium">{user?.display_name || user?.username}</p>
          <p className="text-xs text-gray-400">{user?.role}</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <p className="text-sm text-gray-500">WebSocket</p>
          <p className="text-lg font-medium capitalize">{status}</p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <p className="text-sm text-gray-500">Last Sequence</p>
          <p className="text-lg font-medium font-mono">{lastSequence || "—"}</p>
        </div>
      </div>

      <EventLog />
    </div>
  )
}
