import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Outlet, useMatch } from "react-router-dom"
import { useWebSocket } from "../../core/hooks/useWebSocket"
import { usePersonas } from "../../core/hooks/usePersonas"
import { useChatSessions } from "../../core/hooks/useChatSessions"
import { useAuthStore } from "../../core/store/authStore"
import { useSanitisedMode } from "../../core/store/sanitisedModeStore"
import { useEventBus } from "../../core/hooks/useEventBus"
import { Sidebar } from "../components/sidebar/Sidebar"
import { Topbar } from "../components/topbar/Topbar"
import { UserModal, type UserModalTab } from "../components/user-modal/UserModal"
import { AdminModal, type AdminModalTab } from "../components/admin-modal/AdminModal"
import { Topics } from "../../core/types/events"
import { llmApi } from "../../core/api/llm"
import type { ProviderCredentialDto } from "../../core/types/llm"

export default function AppLayout() {
  useWebSocket()

  const { personas: allPersonas } = usePersonas()
  const { sessions } = useChatSessions()
  const user = useAuthStore((s) => s.user)
  const isSanitised = useSanitisedMode((s) => s.isSanitised)

  const personas = useMemo(
    () => isSanitised ? allPersonas.filter((p) => !p.nsfw) : allPersonas,
    [allPersonas, isSanitised],
  )
  const setUser = useAuthStore((s) => s.setUser)

  const chatMatch = useMatch("/chat/:personaId/:sessionId?")
  const activePersonaId = chatMatch?.params.personaId ?? null
  const activeSessionId = chatMatch?.params.sessionId ?? null

  // User modal state
  const [modalTab, setModalTab] = useState<UserModalTab | null>(null)

  function openModal(tab: UserModalTab) {
    setAdminTab(null)
    setModalTab(tab)
  }

  function closeModal() {
    setModalTab(null)
  }

  // Admin modal state
  const [adminTab, setAdminTab] = useState<AdminModalTab | null>(null)

  function openAdmin() {
    setModalTab(null)
    setAdminTab('users')
  }

  function closeAdmin() {
    setAdminTab(null)
  }

  // Provider / API-key problem detection
  const [providers, setProviders] = useState<ProviderCredentialDto[]>([])
  const autoOpenFired = useRef(false)

  const hasApiKeyProblem = useMemo(() => {
    const configured = providers.filter((p) => p.is_configured)
    if (configured.length === 0) return true
    return configured.some((p) => p.test_status === 'failed')
  }, [providers])

  const fetchProviders = useCallback(async () => {
    try {
      const result = await llmApi.listProviders()
      setProviders(result)
    } catch {
      // Silently fail
    }
  }, [])

  // Fetch providers on mount
  useEffect(() => {
    if (user) fetchProviders()
  }, [user, fetchProviders])

  // Auto-open API-Keys tab once per session if there's a problem
  useEffect(() => {
    if (hasApiKeyProblem && !autoOpenFired.current && user && providers.length > 0) {
      autoOpenFired.current = true
      openModal('api-keys')
    }
  }, [hasApiKeyProblem, user, providers])

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
        onOpenAdmin={openAdmin}
        isAdminOpen={adminTab !== null}
        hasApiKeyProblem={hasApiKeyProblem}
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
              hasApiKeyProblem={hasApiKeyProblem}
              onProvidersChanged={setProviders}
            />
          )}
          {adminTab !== null && (
            <AdminModal
              activeTab={adminTab}
              onClose={closeAdmin}
              onTabChange={setAdminTab}
            />
          )}
        </main>
      </div>
    </div>
  )
}
