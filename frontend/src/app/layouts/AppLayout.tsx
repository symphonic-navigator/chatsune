import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { lockBodyScroll, unlockBodyScroll } from "../../core/utils/bodyScrollLock"
import { Outlet, useLocation, useMatch, useNavigate } from "react-router-dom"
import { useDrawerStore } from "../../core/store/drawerStore"
import { useViewport } from "../../core/hooks/useViewport"
import { useWebSocket } from "../../core/hooks/useWebSocket"
import { usePersonas } from "../../core/hooks/usePersonas"
import { useChatSessions } from "../../core/hooks/useChatSessions"
import { useKnowledgeEvents } from "../../features/knowledge/useKnowledgeEvents"
import { useJobEvents } from "../../features/jobs/useJobEvents"
import { chatApi } from "../../core/api/chat"
import { useAuthStore } from "../../core/store/authStore"
import { useSanitisedMode } from "../../core/store/sanitisedModeStore"
import { useEventBus } from "../../core/hooks/useEventBus"
import { Sidebar } from "../components/sidebar/Sidebar"
import { Topbar } from "../components/topbar/Topbar"
import { UserModal, type UserModalTab } from "../components/user-modal/UserModal"
import { AdminModal, type AdminModalTab } from "../components/admin-modal/AdminModal"
import { PersonaOverlay, type PersonaOverlayTab } from "../components/persona-overlay/PersonaOverlay"
import { ToastContainer } from "../components/toast/ToastContainer"
import { Topics } from "../../core/types/events"
import { llmApi } from "../../core/api/llm"
import { personasApi } from "../../core/api/personas"
import type { ProviderCredentialDto } from "../../core/types/llm"
import type { CreatePersonaRequest, UpdatePersonaRequest } from "../../core/types/persona"

export default function AppLayout() {
  useWebSocket()
  useKnowledgeEvents()
  useJobEvents()
  const navigate = useNavigate()
  const location = useLocation()
  const { isDesktop } = useViewport()
  const drawerOpen = useDrawerStore((s) => s.sidebarOpen)
  const closeDrawer = useDrawerStore((s) => s.close)

  // Close the drawer on every route change while on mobile. This covers all
  // in-drawer navigation (persona clicks, session clicks, NewChat, NavRow),
  // so individual components do not need to dismiss the drawer themselves.
  useEffect(() => {
    if (!isDesktop && drawerOpen) {
      closeDrawer()
    }
    // Intentionally scoped to path changes only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname])

  // Close the drawer on `Esc` while it is open (mobile only).
  useEffect(() => {
    if (isDesktop || !drawerOpen) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeDrawer()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [isDesktop, drawerOpen, closeDrawer])

  // Lock background scroll while the drawer is open on mobile. Uses the
  // shared ref-counted helper so this lock composes cleanly with Sheet
  // components that also lock the body scroll.
  useEffect(() => {
    if (isDesktop || !drawerOpen) return
    lockBodyScroll()
    return () => unlockBodyScroll()
  }, [isDesktop, drawerOpen])

  const { personas: allPersonas, update: updatePersona, reorder: reorderPersonas } = usePersonas()
  const { sessions, updateSession: updateChatSession } = useChatSessions()
  const user = useAuthStore((s) => s.user)
  const isSanitised = useSanitisedMode((s) => s.isSanitised)

  const personas = useMemo(
    () => isSanitised ? allPersonas.filter((p) => !p.nsfw) : allPersonas,
    [allPersonas, isSanitised],
  )

  const nsfwPersonaIds = useMemo(
    () => new Set(allPersonas.filter((p) => p.nsfw).map((p) => p.id)),
    [allPersonas],
  )

  const filteredSessions = useMemo(
    () => isSanitised ? sessions.filter((s) => !nsfwPersonaIds.has(s.persona_id)) : sessions,
    [sessions, isSanitised, nsfwPersonaIds],
  )
  const setUser = useAuthStore((s) => s.setUser)

  const chatMatch = useMatch("/chat/:personaId/:sessionId?")
  const activePersonaId = chatMatch?.params.personaId ?? null
  const activeSessionId = chatMatch?.params.sessionId ?? null

  // User modal state
  const [modalTab, setModalTab] = useState<UserModalTab | null>(null)

  function openModal(tab: UserModalTab) {
    setAdminTab(null)
    setPersonaOverlay(null)
    setModalTab(tab)
  }

  function closeModal() {
    setModalTab(null)
    setAdminTab(null)
    setPersonaOverlay(null)
  }

  // Admin modal state
  const [adminTab, setAdminTab] = useState<AdminModalTab | null>(null)

  function openAdmin() {
    setModalTab(null)
    setPersonaOverlay(null)
    setAdminTab('users')
  }

  function closeAdmin() {
    setAdminTab(null)
  }

  // Persona overlay state
  const [personaOverlay, setPersonaOverlay] = useState<{
    personaId: string | null
    tab: PersonaOverlayTab
  } | null>(null)

  const openPersonaOverlay = useCallback(
    (personaId: string | null, tab: PersonaOverlayTab = "overview") => {
      setModalTab(null)
      setAdminTab(null)
      setPersonaOverlay({ personaId, tab })
    },
    [],
  )

  const closePersonaOverlay = useCallback(() => {
    setPersonaOverlay(null)
  }, [])

  const handlePersonaOverlayTabChange = useCallback(
    (tab: PersonaOverlayTab) => {
      setPersonaOverlay((prev) => (prev ? { ...prev, tab } : null))
    },
    [],
  )

  const handlePersonaSave = useCallback(
    async (personaId: string | null, data: Record<string, unknown>) => {
      if (personaId) {
        await personasApi.update(personaId, data as UpdatePersonaRequest)
      } else {
        const created = await personasApi.create(data as unknown as CreatePersonaRequest)
        setPersonaOverlay({ personaId: created.id, tab: "overview" })
      }
    },
    [],
  )

  const overlayPersona = personaOverlay?.personaId
    ? allPersonas.find((p) => p.id === personaOverlay.personaId) ?? null
    : null

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
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-[100] focus:rounded-md focus:bg-elevated focus:px-3 focus:py-2 focus:text-sm focus:text-white focus:outline focus:outline-2 focus:outline-gold"
      >
        Skip to content
      </a>
      {/* Backdrop behind the off-canvas drawer (mobile only). */}
      {drawerOpen && !isDesktop && (
        <div
          className="fixed inset-0 z-30 bg-black/50 lg:hidden"
          onClick={closeDrawer}
          aria-hidden="true"
        />
      )}
      <nav aria-label="Primary navigation" className="contents">
      <Sidebar
        personas={personas}
        sessions={filteredSessions}
        activePersonaId={activePersonaId}
        activeSessionId={activeSessionId}
        onOpenModal={openModal}
        onCloseModal={closeModal}
        activeModalTab={modalTab}
        onOpenAdmin={openAdmin}
        isAdminOpen={adminTab !== null}
        hasApiKeyProblem={hasApiKeyProblem}
        onOpenOverlay={(personaId, tab) => openPersonaOverlay(personaId, (tab as PersonaOverlayTab) ?? "overview")}
        onTogglePin={(personaId, pinned) => updatePersona(personaId, { pinned })}
        onReorder={reorderPersonas}
        onToggleSessionPin={async (sessionId, pinned) => {
          updateChatSession(sessionId, { pinned })
          try {
            await chatApi.updateSessionPinned(sessionId, pinned)
          } catch {
            updateChatSession(sessionId, { pinned: !pinned })
          }
        }}
      />
      </nav>
      <div className="relative flex min-w-0 flex-1 flex-col">
        <Topbar
          personas={personas}
          onOpenPersonaOverlay={(id) => openPersonaOverlay(id, "overview")}
          hasApiKeyProblem={hasApiKeyProblem}
        />
        <main id="main-content" tabIndex={-1} className="relative flex-1 overflow-auto bg-surface">
          <Outlet context={{ openPersonaOverlay }} />
          {modalTab !== null && (
            <UserModal
              activeTab={modalTab}
              onClose={closeModal}
              onTabChange={setModalTab}
              displayName={displayName}
              hasApiKeyProblem={hasApiKeyProblem}
              onProvidersChanged={setProviders}
              onOpenPersonaOverlay={(id) => {
                closeModal()
                openPersonaOverlay(id, "overview")
              }}
            />
          )}
          {adminTab !== null && (
            <AdminModal
              activeTab={adminTab}
              onClose={closeAdmin}
              onTabChange={setAdminTab}
            />
          )}
          {personaOverlay && (
            <PersonaOverlay
              persona={overlayPersona}
              allPersonas={allPersonas}
              isCreating={personaOverlay.personaId === null}
              activeTab={personaOverlay.tab}
              onClose={closePersonaOverlay}
              onTabChange={handlePersonaOverlayTabChange}
              onSave={handlePersonaSave}
              onNavigate={(path) => navigate(path)}
              sessions={filteredSessions}
            />
          )}
        </main>
      </div>
      <ToastContainer />
    </div>
  )
}
