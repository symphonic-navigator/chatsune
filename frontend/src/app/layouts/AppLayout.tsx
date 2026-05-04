import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useNotificationStore } from "../../core/store/notificationStore"
import { ApiError } from "../../core/api/client"
import { lockBodyScroll, unlockBodyScroll } from "../../core/utils/bodyScrollLock"
import { Outlet, useLocation, useMatch, useNavigate } from "react-router-dom"
import { useDrawerStore } from "../../core/store/drawerStore"
import { useViewport } from "../../core/hooks/useViewport"
import { useWebSocket } from "../../core/hooks/useWebSocket"
import { usePersonas } from "../../core/hooks/usePersonas"
import { useChatSessions } from "../../core/hooks/useChatSessions"
import { useKnowledgeEvents } from "../../features/knowledge/useKnowledgeEvents"
import { useJobEvents } from "../../features/jobs/useJobEvents"
import { usePullProgressEvents } from "../../features/ollama/usePullProgressEvents"
import { useMcpEvents } from "../../features/mcp/useMcpEvents"
import { chatApi } from "../../core/api/chat"
import { useAuthStore } from "../../core/store/authStore"
import { useSanitisedMode } from "../../core/store/sanitisedModeStore"
import { useEventBus } from "../../core/hooks/useEventBus"
import { Sidebar } from "../components/sidebar/Sidebar"
import { Topbar } from "../components/topbar/Topbar"
import { UserModal } from "../components/user-modal/UserModal"
import { resolveLeaf, firstSubOf, type TopTabId, type SubTabId, type LeafId } from "../components/user-modal/userModalTree"
import { useSubtabStore } from "../components/user-modal/userModalSubtabStore"
import { AdminModal, type AdminModalTab } from "../components/admin-modal/AdminModal"
import { PersonaOverlay, type PersonaOverlayTab } from "../components/persona-overlay/PersonaOverlay"
import { ToastContainer } from "../components/toast/ToastContainer"
import { MobileToastContainer } from "../components/toast/MobileToastContainer"
import { InstallHint } from "../components/pwa/InstallHint"
import { VoiceVisualiser } from "../../features/voice/components/VoiceVisualiser"
import { VoiceCountdownPie } from "../../features/voice/components/VoiceCountdownPie"
import { VoiceVisualiserHitStrip } from "../../features/voice/components/VoiceVisualiserHitStrip"
import { personaHex } from "../components/sidebar/personaColour"
import { Topics } from "../../core/types/events"
import { personasApi } from "../../core/api/personas"
import type { CreatePersonaRequest, UpdatePersonaRequest } from "../../core/types/persona"
import { useRecentEmojisStore } from "../../features/chat/recentEmojisStore"
import { useRecentProjectEmojisStore } from "../../features/projects/recentProjectEmojisStore"
import { useProjectOverlayStore } from "../../features/projects/useProjectOverlayStore"
import { ProjectDetailOverlay } from "../../features/projects/ProjectDetailOverlay"
import { BackButtonProvider } from '../../core/back-button/BackButtonProvider'
import { useBackButtonClose, startOverlayTransition } from '../../core/hooks/useBackButtonClose'

export default function AppLayout() {
  useWebSocket()
  useKnowledgeEvents()
  useJobEvents()
  usePullProgressEvents()
  useMcpEvents()
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

  // Browser back closes the off-canvas drawer on mobile only. On desktop
  // the drawer is the permanent rail, so we never push a history entry
  // for it there.
  useBackButtonClose(!isDesktop && drawerOpen, closeDrawer, 'mobile-drawer')

  const { personas: allPersonas, update: updatePersona } = usePersonas()
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
  const activePersonaHex = activePersonaId
    ? personaHex(allPersonas.find((p) => p.id === activePersonaId) ?? { colour_scheme: '' })
    : undefined

  // User modal state
  const [modalOpen, setModalOpen] = useState(false)
  const [activeTop, setActiveTop] = useState<TopTabId>('about-me')
  const [activeSub, setActiveSub] = useState<SubTabId | undefined>(undefined)

  function openModal(leaf: LeafId | string) {
    const { top, sub: resolved } = resolveLeaf(leaf)
    const remembered = useSubtabStore.getState().lastSub[top]
    const sub = resolved ?? remembered ?? firstSubOf(top)
    if (adminTab !== null) startOverlayTransition('admin-modal')
    else if (personaOverlay !== null) startOverlayTransition('persona-overlay')
    else if (projectOverlayId !== null) startOverlayTransition('project-overlay')
    setAdminTab(null)
    setPersonaOverlay(null)
    closeProjectOverlay()
    setActiveTop(top)
    setActiveSub(sub)
    setModalOpen(true)
  }

  function closeModal() {
    setModalOpen(false)
    setAdminTab(null)
    setPersonaOverlay(null)
  }

  function handleTabChange(top: TopTabId, sub?: SubTabId) {
    const finalSub = sub ?? useSubtabStore.getState().lastSub[top] ?? firstSubOf(top)
    setActiveTop(top)
    setActiveSub(finalSub)
    if (finalSub) {
      useSubtabStore.getState().setLastSub(top, finalSub)
    }
  }

  // Admin modal state
  const [adminTab, setAdminTab] = useState<AdminModalTab | null>(null)

  function openAdmin() {
    if (modalOpen) startOverlayTransition('user-modal')
    else if (personaOverlay !== null) startOverlayTransition('persona-overlay')
    else if (projectOverlayId !== null) startOverlayTransition('project-overlay')
    setModalOpen(false)
    setPersonaOverlay(null)
    closeProjectOverlay()
    setAdminTab('users')
  }

  function closeAdmin() {
    setAdminTab(null)
  }

  // Project-Detail-Overlay state — owned by `useProjectOverlayStore`
  // so any surface (sidebar, switcher, modal Projects-tab) can open
  // the same overlay without prop-drilling.
  const projectOverlayId = useProjectOverlayStore((s) => s.projectId)
  const projectOverlayTab = useProjectOverlayStore((s) => s.tab)
  const closeProjectOverlay = useProjectOverlayStore((s) => s.close)

  // Persona overlay state
  const [personaOverlay, setPersonaOverlay] = useState<{
    personaId: string | null
    tab: PersonaOverlayTab
  } | null>(null)

  const openPersonaOverlay = useCallback(
    (personaId: string | null, tab: PersonaOverlayTab = "overview") => {
      if (modalOpen) startOverlayTransition('user-modal')
      else if (adminTab !== null) startOverlayTransition('admin-modal')
      else if (projectOverlayId !== null) startOverlayTransition('project-overlay')
      setModalOpen(false)
      setAdminTab(null)
      closeProjectOverlay()
      setPersonaOverlay({ personaId, tab })
    },
    [modalOpen, adminTab, projectOverlayId, closeProjectOverlay],
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

  // Persona import — shared between PersonasPage and the user-modal Personas tab.
  const addNotification = useNotificationStore((s) => s.addNotification)
  const personaImportFileRef = useRef<HTMLInputElement>(null)
  const [personaImporting, setPersonaImporting] = useState(false)

  const handleImportPersona = useCallback(() => {
    personaImportFileRef.current?.click()
  }, [])

  const handlePersonaFileSelected = useCallback(
    async (event: React.ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0] ?? null
      event.target.value = ""
      if (!file) return

      setPersonaImporting(true)
      try {
        const created = await personasApi.importPersona(file)
        addNotification({
          level: "success",
          title: "Persona imported",
          message: `${created.name} has been imported.`,
        })
        openPersonaOverlay(created.id, "overview")
      } catch (err) {
        const message =
          err instanceof ApiError
            ? err.message
            : err instanceof Error
              ? err.message
              : "Failed to import persona."
        addNotification({
          level: "error",
          title: "Import failed",
          message,
        })
      } finally {
        setPersonaImporting(false)
      }
    },
    [addNotification, openPersonaOverlay],
  )

  // TODO Phase 8: reinstate the API-key problem detection against the new
  // connections endpoint. For now we assume no problem so the UI stays clean.
  const hasApiKeyProblem = false
  const notifyProvidersChanged = useCallback(() => {}, [])

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

  // Seed the recent-emojis store from the authenticated user payload. The
  // `?? []` guards against an older backend that doesn't yet ship the field.
  useEffect(() => {
    if (!user) return
    useRecentEmojisStore.getState().set(user.recent_emojis ?? [])
  }, [user])

  // Live-update the recent emojis when the user picks one in another tab or
  // device. Mirrors the USER_PROFILE_UPDATED subscription style above.
  const { latest: recentEmojisUpdate } = useEventBus(Topics.USER_RECENT_EMOJIS_UPDATED)
  useEffect(() => {
    if (!recentEmojisUpdate?.payload) return
    const emojis = (recentEmojisUpdate.payload as { emojis?: string[] }).emojis
    if (Array.isArray(emojis)) {
      useRecentEmojisStore.getState().set(emojis)
    }
  }, [recentEmojisUpdate])

  // Mindspace: same pattern for the project-emoji LRU. Seeded from the
  // authenticated user payload, then kept in sync via
  // USER_RECENT_PROJECT_EMOJIS_UPDATED. The backend does not currently
  // emit that topic — Phase 5 wires the frontend store only; persistence
  // and event emission land in a later Mindspace phase. Until then the
  // subscription is harmlessly idle.
  useEffect(() => {
    if (!user) return
    useRecentProjectEmojisStore.getState().set(user.recent_project_emojis ?? [])
  }, [user])

  const { latest: recentProjectEmojisUpdate } = useEventBus(
    Topics.USER_RECENT_PROJECT_EMOJIS_UPDATED,
  )
  useEffect(() => {
    if (!recentProjectEmojisUpdate?.payload) return
    const emojis = (recentProjectEmojisUpdate.payload as { emojis?: string[] }).emojis
    if (Array.isArray(emojis)) {
      useRecentProjectEmojisStore.getState().set(emojis)
    }
  }, [recentProjectEmojisUpdate])

  // Global Alt+S hotkey: toggles sanitised mode irrespective of which modal
  // or overlay is currently open. We only bow out if the user is actively
  // editing text (input/textarea/contenteditable) so we never hijack typing.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!event.altKey || event.key.toLowerCase() !== 's') return
      const target = event.target as HTMLElement | null
      if (target) {
        const tag = target.tagName
        if (tag === 'INPUT' || tag === 'TEXTAREA' || target.isContentEditable) {
          return
        }
      }
      event.preventDefault()
      event.stopPropagation()
      useSanitisedMode.getState().toggle()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // When sanitised mode flips OFF -> ON while the user is currently viewing a
  // chat with an NSFW persona, push them out to that persona's overview so
  // they are no longer staring at NSFW content. ON -> OFF never navigates.
  const prevSanitisedRef = useRef(isSanitised)
  useEffect(() => {
    const prev = prevSanitisedRef.current
    prevSanitisedRef.current = isSanitised
    if (prev || !isSanitised) return
    if (!activePersonaId) return
    const persona = allPersonas.find((p) => p.id === activePersonaId)
    if (persona?.nsfw) {
      openPersonaOverlay(activePersonaId, 'overview')
    }
  }, [isSanitised, activePersonaId, allPersonas, openPersonaOverlay])

  const displayName = user?.display_name || user?.username || 'Unnamed User'

  return (
    <BackButtonProvider>
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
        activeModalTop={modalOpen ? activeTop : null}
        activeModalSub={modalOpen ? activeSub ?? null : null}
        onOpenAdmin={openAdmin}
        isAdminOpen={adminTab !== null}
        hasApiKeyProblem={hasApiKeyProblem}
        onOpenOverlay={(personaId, tab) => openPersonaOverlay(personaId, (tab as PersonaOverlayTab) ?? "overview")}
        onTogglePin={(personaId, pinned) => updatePersona(personaId, { pinned })}
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
          sessions={sessions}
          onOpenPersonaOverlay={(id) => openPersonaOverlay(id, "overview")}
          hasApiKeyProblem={hasApiKeyProblem}
        />
        <main id="main-content" tabIndex={-1} className="relative flex-1 overflow-auto bg-surface">
          <Outlet context={{ openPersonaOverlay, openModal }} />
          {modalOpen && (
            <UserModal
              activeTop={activeTop}
              activeSub={activeSub}
              onClose={closeModal}
              onTabChange={handleTabChange}
              displayName={displayName}
              hasApiKeyProblem={hasApiKeyProblem}
              onProvidersChanged={notifyProvidersChanged}
              onOpenPersonaOverlay={(id) => openPersonaOverlay(id, "overview")}
              onCreatePersona={() => openPersonaOverlay(null, "edit")}
              onImportPersona={handleImportPersona}
            />
          )}
          {adminTab !== null && (
            <AdminModal
              activeTab={adminTab}
              onClose={closeAdmin}
              onTabChange={setAdminTab}
            />
          )}
          {projectOverlayId && (
            <ProjectDetailOverlay
              projectId={projectOverlayId}
              initialTab={projectOverlayTab}
              onClose={closeProjectOverlay}
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
          <VoiceVisualiserHitStrip />
        </main>
      </div>
      <VoiceVisualiser personaColourHex={activePersonaHex} />
      <VoiceCountdownPie personaColourHex={activePersonaHex} />
      <ToastContainer />
      <MobileToastContainer />
      <InstallHint />
      <input
        ref={personaImportFileRef}
        type="file"
        accept=".tar.gz,.gz,application/gzip"
        className="hidden"
        onChange={handlePersonaFileSelected}
      />
      {personaImporting && (
        <div
          className="fixed inset-0 z-[55] flex items-center justify-center bg-black/60"
          role="status"
          aria-live="polite"
          aria-label="Importing persona"
        >
          <div className="flex items-center gap-3 rounded-lg border border-white/8 bg-elevated px-5 py-4 shadow-2xl">
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-gold/30 border-t-gold" />
            <span className="text-[13px] text-white/80">Importing persona…</span>
          </div>
        </div>
      )}
    </div>
    </BackButtonProvider>
  )
}
