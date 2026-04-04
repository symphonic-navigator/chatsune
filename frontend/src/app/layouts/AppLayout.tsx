import { useEffect, useState } from "react"
import { Outlet, useMatch } from "react-router-dom"
import { useWebSocket } from "../../core/hooks/useWebSocket"
import { usePersonas } from "../../core/hooks/usePersonas"
import { useChatSessions } from "../../core/hooks/useChatSessions"
import { useAuthStore } from "../../core/store/authStore"
import { useEventBus } from "../../core/hooks/useEventBus"
import { Sidebar } from "../components/sidebar/Sidebar"
import { Topbar } from "../components/topbar/Topbar"
import { UserModal, type UserModalTab } from "../components/user-modal/UserModal"
import { Topics } from "../../core/types/events"

export default function AppLayout() {
  useWebSocket()

  const { personas } = usePersonas()
  const { sessions } = useChatSessions()
  const user = useAuthStore((s) => s.user)
  const setUser = useAuthStore((s) => s.setUser)

  const chatMatch = useMatch("/chat/:personaId/:sessionId?")
  const activePersonaId = chatMatch?.params.personaId ?? null
  const activeSessionId = chatMatch?.params.sessionId ?? null

  const [modalTab, setModalTab] = useState<UserModalTab | null>(null)

  function openModal(tab: UserModalTab) {
    setModalTab(tab)
  }

  function closeModal() {
    setModalTab(null)
  }

  // Live-update display name when user changes it in another tab or device
  const { latest: profileUpdate } = useEventBus(Topics.USER_PROFILE_UPDATED)
  useEffect(() => {
    if (!profileUpdate) return
    const rawName = (profileUpdate.payload as Record<string, unknown>).display_name
    if (typeof rawName !== 'string') return
    const current = useAuthStore.getState().user
    if (!current) return
    setUser({ ...current, display_name: rawName })
  }, [profileUpdate, setUser])

  const displayName = user?.display_name || user?.username || 'Unnamed User'

  return (
    <div className="flex h-full overflow-hidden bg-base text-white">
      <Sidebar
        personas={personas}
        sessions={sessions}
        activePersonaId={activePersonaId}
        activeSessionId={activeSessionId}
        onOpenModal={openModal}
        onCloseModal={closeModal}
        activeModalTab={modalTab}
      />
      <div className="relative flex min-w-0 flex-1 flex-col">
        <Topbar personas={personas} />
        <main className="relative flex-1 overflow-auto bg-surface">
          <Outlet />
          {modalTab !== null && (
            <UserModal
              activeTab={modalTab}
              onClose={closeModal}
              onTabChange={setModalTab}
              displayName={displayName}
            />
          )}
        </main>
      </div>
    </div>
  )
}
