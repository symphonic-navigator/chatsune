import { Outlet, useMatch } from "react-router-dom"
import { useWebSocket } from "../../core/hooks/useWebSocket"
import { usePersonas } from "../../core/hooks/usePersonas"
import { useChatSessions } from "../../core/hooks/useChatSessions"
import { Sidebar } from "../components/sidebar/Sidebar"
import { Topbar } from "../components/topbar/Topbar"

export default function AppLayout() {
  useWebSocket()

  const { personas } = usePersonas()
  const { sessions } = useChatSessions()

  const chatMatch = useMatch("/chat/:personaId/:sessionId?")
  const activePersonaId = chatMatch?.params.personaId ?? null
  const activeSessionId = chatMatch?.params.sessionId ?? null

  return (
    <div className="flex h-screen overflow-hidden bg-base text-white">
      <Sidebar
        personas={personas}
        sessions={sessions}
        activePersonaId={activePersonaId}
        activeSessionId={activeSessionId}
      />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar personas={personas} />
        <main className="flex-1 overflow-auto bg-surface">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
