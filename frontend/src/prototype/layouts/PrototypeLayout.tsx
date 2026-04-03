import { NavLink, Outlet } from "react-router-dom"
import { useAuthStore } from "../../core/store/authStore"
import { useAuth } from "../../core/hooks/useAuth"
import { useEventStore, type ConnectionStatus } from "../../core/store/eventStore"
import StatusBar from "../components/StatusBar"

const statusColours: Record<ConnectionStatus, string> = {
  connected: "bg-green-500",
  connecting: "bg-yellow-500",
  reconnecting: "bg-yellow-500",
  disconnected: "bg-red-500",
}

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `block rounded px-3 py-2 text-sm ${isActive ? "bg-gray-200 font-medium" : "text-gray-600 hover:bg-gray-100"}`

export default function PrototypeLayout() {
  const user = useAuthStore((s) => s.user)
  const status = useEventStore((s) => s.status)
  const { logout } = useAuth()
  const isAdmin = user?.role === "admin" || user?.role === "master_admin"

  return (
    <div className="flex h-screen bg-gray-50">
      {/* Sidebar */}
      <aside className="flex w-56 flex-col border-r border-gray-200 bg-white">
        <div className="border-b border-gray-200 px-4 py-4">
          <h1 className="text-lg font-semibold">Chatsune</h1>
          <p className="text-xs text-gray-400">Prototype</p>
        </div>

        <nav className="flex-1 space-y-1 p-3">
          <NavLink to="/dashboard" className={navLinkClass}>Dashboard</NavLink>
          {isAdmin && <NavLink to="/users" className={navLinkClass}>Users</NavLink>}
          <NavLink to="/llm" className={navLinkClass}>LLM</NavLink>
          <NavLink to="/personas" className={navLinkClass}>Personas</NavLink>
          {isAdmin && <NavLink to="/admin" className={navLinkClass}>Admin</NavLink>}
        </nav>

        <div className="border-t border-gray-200 p-3 space-y-2">
          <div className="flex items-center gap-2 px-1">
            <span className={`inline-block h-2 w-2 rounded-full ${statusColours[status]}`} />
            <span className="text-xs text-gray-500">{status}</span>
          </div>
          <div className="px-1">
            <p className="text-sm font-medium">{user?.display_name || user?.username}</p>
            <p className="text-xs text-gray-400">{user?.role}</p>
          </div>
          <button
            onClick={logout}
            className="w-full rounded px-3 py-1.5 text-left text-sm text-gray-600 hover:bg-gray-100"
          >
            Logout
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex flex-1 flex-col overflow-hidden">
        <StatusBar />
        <div className="flex-1 overflow-auto p-6">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
