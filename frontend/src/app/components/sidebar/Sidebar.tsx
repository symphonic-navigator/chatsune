import { Fragment, useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { useAuthStore } from "../../../core/store/authStore"
import { useNotificationStore } from "../../../core/store/notificationStore"
import { useSanitisedMode } from "../../../core/store/sanitisedModeStore"
import { useSidebarStore } from "../../../core/store/sidebarStore"
import { useDrawerStore } from "../../../core/store/drawerStore"
import { useHistoryStackStore } from "../../../core/store/historyStackStore"
import { useViewport } from "../../../core/hooks/useViewport"
import { useAuth } from "../../../core/hooks/useAuth"
import { startOverlayTransition } from "../../../core/hooks/useBackButtonClose"
import { SidebarFlyout } from './SidebarFlyout'
import { PersonaItem } from "./PersonaItem"
import { HistoryItem } from "./HistoryItem"
import { ProjectSidebarItem } from "./ProjectSidebarItem"
import { useFilteredPinnedProjects } from "../../../features/projects/useProjectsStore"
import { projectsApi } from "../../../features/projects/projectsApi"
import { useProjectOverlayStore } from "../../../features/projects/useProjectOverlayStore"
import { MobileSidebarHeader } from './MobileSidebarHeader'
import { MobileMainView } from './MobileMainView'
import { MobileNewChatView } from './MobileNewChatView'
import { MobileProjectsView } from './MobileProjectsView'
import { HistoryTab } from '../user-modal/HistoryTab'
import { BookmarksTab } from '../user-modal/BookmarksTab'
import type { PersonaDto } from "../../../core/types/persona"
import { chatApi, type ChatSessionDto } from "../../../core/api/chat"
import type { TopTabId, SubTabId } from "../user-modal/userModalTree"
import { ActionBlock } from './ActionBlock'
import { ZoneSection } from './ZoneSection'
import { FooterBlock } from './FooterBlock'
import { PROJECTS_ENABLED } from '../../../core/config/featureGates'
import { ProjectCreateModal } from '../../../features/projects/ProjectCreateModal'
import { sortPersonas } from './personaSort'
import { getLastMyDataSubpage } from '../user-modal/myDataMemory'
import { BookmarkIcon, CollegeIcon, FoxIcon, LockClosedIcon, LockOpenIcon } from '../../../core/components/symbols'

interface SidebarProps {
  personas: PersonaDto[]
  sessions: ChatSessionDto[]
  activePersonaId: string | null
  activeSessionId: string | null
  onOpenModal: (leaf: string) => void
  onCloseModal: () => void
  activeModalTop: TopTabId | null
  activeModalSub: SubTabId | null
  onOpenAdmin: () => void
  isAdminOpen: boolean
  hasApiKeyProblem: boolean
  onOpenOverlay?: (personaId: string, tab?: string) => void
  onTogglePin?: (personaId: string, pinned: boolean) => void
  onToggleSessionPin?: (sessionId: string, pinned: boolean) => void
}

function IconBtn({
  icon,
  onClick,
  title,
  isActive,
  className = "",
}: {
  icon: React.ReactNode
  onClick: () => void
  title: string
  isActive?: boolean
  className?: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-label={title}
      className={[
        "flex h-11 w-11 lg:h-8 lg:w-8 items-center justify-center rounded-lg text-sm transition-colors hover:bg-white/8",
        isActive ? "text-gold" : "text-white/60",
        className,
      ].join(" ")}
    >
      {icon}
    </button>
  )
}

function PinnedDivider() {
  return (
    <div className="mx-auto my-1 h-px w-12 bg-white/10" aria-hidden="true" />
  )
}

export function Sidebar({
  personas,
  sessions,
  activePersonaId,
  activeSessionId,
  onOpenModal,
  onCloseModal,
  activeModalTop,
  activeModalSub,
  onOpenAdmin,
  isAdminOpen,
  hasApiKeyProblem,
  onOpenOverlay,
  onTogglePin,
  onToggleSessionPin,
}: SidebarProps) {
  const user = useAuthStore((s) => s.user)
  const { isSanitised, toggle: toggleSanitised } = useSanitisedMode()
  const { isCollapsed, toggle: toggleCollapsed } = useSidebarStore()
  const { isDesktop } = useViewport()
  const drawerOpen = useDrawerStore((s) => s.sidebarOpen)
  // Rail/full toggle is a desktop-only affordance. Below `lg` the sidebar is
  // always rendered in its full form inside the off-canvas drawer.
  const renderCollapsed = isDesktop && isCollapsed
  const { logout } = useAuth()
  const navigate = useNavigate()
  const addNotification = useNotificationStore((s) => s.addNotification)

  const isAdmin = user?.role === "admin" || user?.role === "master_admin"
  const isInChat = !!activePersonaId
  const lastSession = sessions[0] ?? null

  // Projects collapse-state removed alongside hidden Projects UI (see FOR_LATER.md).

  const [historySearch, setHistorySearch] = useState("")

  // Projects flyout is hidden (see FOR_LATER.md), so the flyout tab type is
  // currently history-only. Keep the union shape so re-enabling Projects later
  // is a one-line widening rather than reshaping every callsite.
  const [flyoutTab, setFlyoutTab] = useState<'history' | null>(null)

  type MobileView = 'main' | 'new-chat' | 'history' | 'bookmarks' | 'projects'
  const [mobileView, setMobileView] = useState<MobileView>('main')

  const [createProjectOpen, setCreateProjectOpen] = useState(false)

  // Reset to main when the drawer is closed (so next open lands on main view).
  useEffect(() => {
    if (!drawerOpen) setMobileView('main')
  }, [drawerOpen])

  function toggleFlyout(tab: 'history') {
    setFlyoutTab((prev) => {
      if (prev === tab) {
        setHistorySearch("")
        return null
      }
      return tab
    })
  }

  function openFullViewFromFlyout(tab: 'history') {
    setFlyoutTab(null)
    onOpenModal(tab)
  }

  const sortedPersonas = useMemo(
    () => sortPersonas(personas),
    [personas],
  )

  // Mindspace §6.7: pinned projects in sanitised mode hide NSFW
  // projects across every sidebar render path.
  const pinnedProjects = useFilteredPinnedProjects()

  const sortedSessions = useMemo(() => {
    const pinned = sessions.filter((s) => s.pinned)
    const unpinned = sessions.filter((s) => !s.pinned)
    const byUpdated = (a: ChatSessionDto, b: ChatSessionDto) => b.updated_at.localeCompare(a.updated_at)
    pinned.sort(byUpdated)
    unpinned.sort(byUpdated)
    return [...pinned, ...unpinned]
  }, [sessions])

  // On mobile the sidebar lives in an off-canvas drawer; once the user has
  // picked something, collapse it automatically so the chat is visible.
  // Desktop keeps the sidebar open — there is enough room for both.
  function closeDrawerIfMobile() {
    if (!isDesktop) {
      startOverlayTransition('mobile-drawer')
      useHistoryStackStore.getState().remove('mobile-drawer')
      useDrawerStore.getState().close()
    }
  }

  /** Close any mobile overlay AND the drawer itself. Used by item-tap in
   *  History/Bookmarks/New-Chat to fully collapse. */
  function closeOverlayAndDrawer() {
    setMobileView('main')
    if (!isDesktop) {
      startOverlayTransition('mobile-drawer')
      useHistoryStackStore.getState().remove('mobile-drawer')
      useDrawerStore.getState().close()
    }
  }

  /** Open a modal tab and dismiss the mobile drawer. */
  function openModalAndClose(leaf: string) {
    closeDrawerIfMobile()
    onOpenModal(leaf)
  }

  /** Open the persona overlay and dismiss the mobile drawer. */
  function openOverlayAndClose(personaId: string, tab?: string) {
    closeDrawerIfMobile()
    onOpenOverlay?.(personaId, tab)
  }

  function handleOpenMyData() {
    closeDrawerIfMobile()
    onOpenModal(getLastMyDataSubpage())
  }

  function handlePersonaSelect(persona: PersonaDto) {
    onCloseModal()
    closeDrawerIfMobile()
    navigate(`/chat/${persona.id}`, !isDesktop ? { replace: true } : undefined)
  }

  function handleNewChat(persona: PersonaDto) {
    onCloseModal()
    closeDrawerIfMobile()
    navigate(`/chat/${persona.id}?new=1`, !isDesktop ? { replace: true } : undefined)
  }

  function handleNewChatFromMobileOverlay(persona: PersonaDto, opts: { incognito: boolean }) {
    onCloseModal()
    setMobileView('main')
    closeDrawerIfMobile()
    const query = opts.incognito ? 'incognito=1' : 'new=1'
    navigate(`/chat/${persona.id}?${query}`, { replace: true })
  }

  function handleSessionClick(session: ChatSessionDto) {
    onCloseModal()
    closeDrawerIfMobile()
    navigate(
      `/chat/${session.persona_id}/${session.id}`,
      !isDesktop ? { replace: true } : undefined,
    )
  }

  function handleContinue() {
    if (!lastSession) return
    onCloseModal()
    closeDrawerIfMobile()
    navigate(
      `/chat/${lastSession.persona_id}/${lastSession.id}`,
      !isDesktop ? { replace: true } : undefined,
    )
  }

  const historyTerm = historySearch.trim().toLowerCase()

  function matchesHistorySearch(s: ChatSessionDto): boolean {
    if (!historyTerm) return true
    const personaName = personas.find((p) => p.id === s.persona_id)?.name ?? s.persona_id
    const title = s.title ?? ''
    return (
      personaName.toLowerCase().includes(historyTerm) ||
      title.toLowerCase().includes(historyTerm) ||
      s.id.toLowerCase().includes(historyTerm)
    )
  }

  const pinnedSessions = sessions.filter((s) => s.pinned && matchesHistorySearch(s))
  const unpinnedSessions = sessions.filter((s) => !s.pinned && matchesHistorySearch(s))

  function handleToggleSessionPin(session: ChatSessionDto, pinned: boolean) {
    onToggleSessionPin?.(session.id, pinned)
  }

  async function handleRenameSession(session: ChatSessionDto, title: string) {
    try {
      await chatApi.updateSession(session.id, { title })
      // No optimistic update needed: useChatSessions subscribes to
      // ChatSessionTitleUpdatedEvent and updates state when it arrives.
    } catch {
      addNotification({
        level: 'error',
        title: 'Rename failed',
        message: 'Could not rename the session.',
      })
    }
  }

  async function handleDeleteSession(session: ChatSessionDto) {
    const wasActive = session.id === activeSessionId
    try {
      await chatApi.deleteSession(session.id)
      if (wasActive) navigate('/personas')
      addNotification({
        level: "success",
        title: "Session deleted",
        message: session.title || "Untitled session",
        duration: 8000,
        action: {
          label: "Undo",
          onClick: () => {
            chatApi.restoreSession(session.id).catch(() => {
              addNotification({
                level: "error",
                title: "Restore failed",
                message: "Could not restore the session.",
              })
            })
          },
        },
      })
    } catch {
      addNotification({
        level: "error",
        title: "Delete failed",
        message: "Could not delete the session.",
      })
    }
  }

  // ── Project handlers ─────────────────────────────────────────────────
  // The detail-overlay (Phase 9) and create-modal (Phase 7) are wired
  // here. The delete-modal placeholder remains a Phase-12 stub.

  function handleOpenProject(projectId: string) {
    closeDrawerIfMobile()
    useProjectOverlayStore.getState().open(projectId)
  }

  function handleEditProject(projectId: string) {
    closeDrawerIfMobile()
    useProjectOverlayStore.getState().open(projectId, 'overview')
  }

  function handleDeleteProject(projectId: string) {
    closeDrawerIfMobile()
    // TODO Phase 12: open DeleteProjectModal
    console.info('TODO Phase 12: open DeleteProjectModal', projectId)
  }

  function handleOpenProjectCreateModal() {
    closeDrawerIfMobile()
    setCreateProjectOpen(true)
  }

  async function handleToggleProjectPin(projectId: string, pinned: boolean) {
    try {
      await projectsApi.setPinned(projectId, pinned)
      // No optimistic update needed: useProjectsStore subscribes to
      // PROJECT_PINNED_UPDATED and reconciles when the event arrives.
    } catch {
      addNotification({
        level: 'error',
        title: pinned ? 'Pin failed' : 'Unpin failed',
        message: 'Could not update the project pin state.',
      })
    }
  }

  const isTabActive = (leaf: string): boolean => {
    if (activeModalTop === null) return false
    if (activeModalSub === leaf) return true           // sub-tab match
    if (activeModalTop === leaf) return true           // top match (with or without sub)
    return false
  }

  // Avatar click opens 'api-keys' leaf (resolves to settings→api-keys) on problem,
  // otherwise opens 'about-me'. Resolution happens inside AppLayout via resolveLeaf.
  const avatarTab: string = hasApiKeyProblem ? 'api-keys' : 'about-me'

  const avatarHighlight =
    activeModalTop === 'about-me' || activeModalTop === 'settings'

  const displayName = user?.display_name || user?.username || 'Unnamed User'
  const initial = displayName.charAt(0).toUpperCase()

  // The Project-Create-Modal lives in the React tree alongside the
  // sidebar so the empty-state "+ Create project" tap can summon it
  // from any of the three sidebar render paths (collapsed / mobile /
  // desktop). Sheet uses a portal under the hood, so the JSX
  // location only matters for state ownership, not visual layering.
  const projectCreateModal = (
    <ProjectCreateModal
      isOpen={createProjectOpen}
      onClose={() => setCreateProjectOpen(false)}
      onCreated={() => setCreateProjectOpen(false)}
    />
  )

  // ── Collapsed view ──────────────────────────────────────────────
  if (renderCollapsed) {
    return (
      <>
      <aside className="flex h-full w-[50px] flex-shrink-0 flex-col items-center border-r border-white/6 bg-base py-2 gap-0.5">
        {/* Logo — expand */}
        <button
          type="button"
          onClick={() => { setFlyoutTab(null); setHistorySearch(""); toggleCollapsed() }}
          title="Expand sidebar"
          aria-label="Expand sidebar"
          className="group flex h-[34px] w-[34px] items-center justify-center rounded-lg text-[17px] transition-colors hover:bg-white/8"
        >
          <span className="group-hover:hidden inline-flex"><FoxIcon style={{ fontSize: '17px' }} /></span>
          <span className="hidden group-hover:inline">⏩</span>
        </button>

        <div className="mx-auto my-1 h-px w-6 bg-white/4" />

        {/* Admin */}
        {isAdmin && (
          <IconBtn
            icon="🪄"
            onClick={onOpenAdmin}
            title="Admin"
            isActive={isAdminOpen}
          />
        )}

        {/* Personas */}
        <IconBtn
          icon="💞"
          onClick={() => { onCloseModal(); navigate("/personas") }}
          title="Personas"
        />

        {/* Continue — hidden when in chat */}
        {!isInChat && lastSession && (
          <IconBtn
            icon="▶️"
            onClick={handleContinue}
            title="Continue last chat"
          />
        )}

        <div className="mx-auto my-1 h-px w-6 bg-white/4" />

        {/* Projects entry point hidden — feature not yet ready (see FOR_LATER.md) */}

        {/* History */}
        <IconBtn
          icon="📖"
          onClick={() => toggleFlyout('history')}
          title="History"
          isActive={isTabActive('history') || flyoutTab === 'history'}
        />

        {/* Spacer */}
        <div className="flex-1" />

        {/* Knowledge */}
        <IconBtn
          icon={<CollegeIcon />}
          onClick={() => onOpenModal('knowledge')}
          title="Knowledge"
          isActive={isTabActive('knowledge')}
        />

        {/* Bookmarks */}
        <IconBtn
          icon={<BookmarkIcon />}
          onClick={() => onOpenModal('bookmarks')}
          title="Bookmarks"
          isActive={isTabActive('bookmarks')}
        />

        {/* My data — combined entry point */}
        <IconBtn
          icon="📂"
          onClick={() => onOpenModal(getLastMyDataSubpage())}
          title="My data"
          isActive={isTabActive('uploads') || isTabActive('artefacts') || isTabActive('images')}
        />

        <div className="mx-auto my-1 h-px w-6 bg-white/4" />

        {/* Sanitised */}
        <button
          type="button"
          onClick={toggleSanitised}
          title={isSanitised ? "Click to turn sanitised mode off" : "Click to turn sanitised mode on"}
          aria-label={isSanitised ? "Turn sanitised mode off" : "Turn sanitised mode on"}
          aria-pressed={isSanitised}
          className="flex h-8 w-8 items-center justify-center rounded-lg text-sm transition-colors hover:bg-white/8"
        >
          {isSanitised ? <LockClosedIcon /> : <LockOpenIcon className="opacity-60" />}
        </button>

        <div className="mx-auto my-1 h-px w-6 bg-white/4" />

        {/* User avatar */}
        <button
          type="button"
          onClick={() => onOpenModal(avatarTab)}
          title={displayName}
          aria-label={`Open profile for ${displayName}`}
          className={[
            "relative flex h-8 w-8 items-center justify-center rounded-full text-[11px] font-bold text-white transition-colors",
            avatarHighlight ? "ring-1 ring-gold" : "",
          ].join(" ")}
          style={{ background: "linear-gradient(to bottom right, var(--purple), var(--gold))" }}
        >
          {initial}
          {hasApiKeyProblem && (
            <span className="absolute -top-0.5 -right-0.5 flex h-3 w-3 items-center justify-center rounded-full bg-red-500 text-[7px] font-bold text-white">!</span>
          )}
        </button>

        {/* Logout */}
        <button
          type="button"
          onClick={() => logout()}
          title="Log out"
          aria-label="Log out"
          className="flex h-8 w-8 items-center justify-center rounded-lg text-[11px] text-white/60 transition-colors hover:bg-white/8 hover:text-white/85"
        >
          ↪
        </button>

        {/* Flyout panels */}
        {flyoutTab === 'history' && (
          <SidebarFlyout
            title="History"
            onClose={() => setFlyoutTab(null)}
            onOpenFullView={() => openFullViewFromFlyout('history')}
          >
            {sessions.length > 0 && (
              <div className="mx-2 mt-1 mb-0.5">
                <input
                  type="text"
                  value={historySearch}
                  onChange={(e) => setHistorySearch(e.target.value)}
                  placeholder="Filter sessions..."
                  className="w-full rounded-md border border-white/6 bg-white/4 px-2 py-1 text-[11px] text-white/70 placeholder-white/55 outline-none transition-colors focus:border-white/12 focus:bg-white/6"
                />
              </div>
            )}
            <div className="mt-0.5 pb-2">
              {pinnedSessions.length > 0 && (
                <>
                  <div className="px-3 py-1.5 text-[10px] uppercase tracking-wider text-white/60">Pinned</div>
                  {pinnedSessions.map((s) => {
                    const persona = personas.find((p) => p.id === s.persona_id)
                    return (
                      <button
                        key={s.id}
                        type="button"
                        onClick={() => { handleSessionClick(s); setFlyoutTab(null) }}
                        className={`mx-2 mb-0.5 flex w-[calc(100%-16px)] flex-col rounded-md px-2.5 py-2 text-left transition-colors ${
                          s.id === activeSessionId ? 'bg-white/8' : 'hover:bg-white/5'
                        }`}
                      >
                        <span className="truncate text-[12px] text-white/70">{s.title ?? 'Untitled session'}</span>
                        <span className="text-[10px] text-white/60">{persona?.name}</span>
                      </button>
                    )
                  })}
                  <div className="mx-3 my-1 h-px bg-white/4" />
                </>
              )}

              <div className="px-3 py-1.5 text-[10px] uppercase tracking-wider text-white/60">Recent</div>
              {unpinnedSessions.map((s) => {
                const persona = personas.find((p) => p.id === s.persona_id)
                return (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => { handleSessionClick(s); setFlyoutTab(null) }}
                    className={`mx-2 mb-0.5 flex w-[calc(100%-16px)] flex-col rounded-md px-2.5 py-2 text-left transition-colors ${
                      s.id === activeSessionId ? 'bg-white/8' : 'hover:bg-white/5'
                    }`}
                  >
                    <span className="truncate text-[12px] text-white/70">{s.title ?? 'Untitled session'}</span>
                    <span className="text-[10px] text-white/25">{persona?.name}</span>
                  </button>
                )
              })}

              {sessions.length === 0 && (
                <p className="px-4 py-3 text-center text-[12px] text-white/60">No history yet</p>
              )}
              {sessions.length > 0 && pinnedSessions.length === 0 && unpinnedSessions.length === 0 && (
                <p className="px-4 py-3 text-center text-[12px] text-white/60">No matching sessions</p>
              )}
            </div>
          </SidebarFlyout>
        )}

        {/* Projects flyout hidden — feature not yet ready (see FOR_LATER.md) */}
      </aside>
      {projectCreateModal}
      </>
    )
  }

  // ── Mobile branch ───────────────────────────────────────────────────
  if (!isDesktop) {
    const handleAdmin     = () => { closeDrawerIfMobile(); onOpenAdmin() }
    const handlePersonas  = () => { onCloseModal(); closeDrawerIfMobile(); navigate('/personas', { replace: true }) }
    const handleKnowledge = () => openModalAndClose('knowledge')
    const handleMyData    = () => openModalAndClose('my-data')
    const handleUserRow   = () => openModalAndClose(avatarTab)
    const handleClose     = () => useDrawerStore.getState().close()

    const overlayTitle =
      mobileView === 'new-chat'  ? 'New Chat'  :
      mobileView === 'history'   ? 'History'   :
      mobileView === 'bookmarks' ? 'Bookmarks' :
      mobileView === 'projects'  ? 'Projects'  :
      undefined

    function handleMobileProjectSelect(projectId: string) {
      // Close the drawer first, then route into the (still-pending)
      // Project-Detail-Overlay. The desktop equivalent does the same
      // via `handleOpenProject`.
      setMobileView('main')
      handleOpenProject(projectId)
    }

    return (
      <>
      <aside
        className={[
          'fixed inset-y-0 left-0 z-40 flex h-full w-full flex-col overflow-hidden border-r border-white/6 bg-base transition-transform duration-200 ease-out',
          drawerOpen ? 'translate-x-0' : '-translate-x-full',
        ].join(' ')}
      >
        <MobileSidebarHeader
          title={overlayTitle}
          onBack={overlayTitle ? () => setMobileView('main') : undefined}
          onClose={handleClose}
        />

        <div className="relative flex-1 overflow-hidden">
          {/* 200%-wide flex with two 50%-wide panels side-by-side; translate
              −50% slides the second panel into view. CSS-only animation. */}
          <div
            className="flex h-full w-[200%] transition-transform duration-150 ease-out"
            style={{ transform: mobileView === 'main' ? 'translateX(0)' : 'translateX(-50%)' }}
          >
            <div className="h-full w-1/2 flex-shrink-0 overflow-hidden">
              <MobileMainView
                isAdmin={isAdmin}
                isInChat={isInChat}
                hasLastSession={!!lastSession}
                hasApiKeyProblem={hasApiKeyProblem}
                isSanitised={isSanitised}
                avatarHighlight={avatarHighlight}
                displayName={displayName}
                role={user?.role || ''}
                initial={initial}
                onAdmin={handleAdmin}
                onContinue={handleContinue}
                onNewChat={() => setMobileView('new-chat')}
                onPersonas={handlePersonas}
                onProjects={() => setMobileView('projects')}
                onHistory={() => setMobileView('history')}
                onBookmarks={() => setMobileView('bookmarks')}
                onKnowledge={handleKnowledge}
                onMyData={handleMyData}
                onToggleSanitised={toggleSanitised}
                onUserRow={handleUserRow}
                onOpenSettings={() => openModalAndClose('settings')}
                onLogout={() => logout()}
              />
            </div>

            <div className="h-full w-1/2 flex-shrink-0 overflow-hidden">
              {mobileView === 'new-chat'  && <MobileNewChatView personas={personas} onSelect={handleNewChatFromMobileOverlay} onClose={closeOverlayAndDrawer} />}
              {mobileView === 'history'   && <HistoryTab   onClose={closeOverlayAndDrawer} />}
              {mobileView === 'bookmarks' && <BookmarksTab onClose={closeOverlayAndDrawer} />}
              {mobileView === 'projects'  && <MobileProjectsView onSelect={handleMobileProjectSelect} />}
            </div>
          </div>
        </div>
      </aside>
      {projectCreateModal}
      </>
    )
  }

  // ── Desktop expanded view ──────────────────────────────────────────────
  return (
    <>
    <aside
      className={[
        // Mobile / tablet: off-canvas drawer. Transform slides it in from
        // the left; `fixed` lifts it out of the flex flow so the main
        // content takes the full width beneath the backdrop.
        "fixed inset-y-0 left-0 z-40 flex h-full w-[85vw] max-w-[320px] flex-col overflow-hidden border-r border-white/6 bg-base transition-transform duration-200 ease-out",
        drawerOpen ? "translate-x-0" : "-translate-x-full",
        // Desktop (`lg` and up): permanent in-flow sidebar, identical to
        // the pre-responsive layout. `lg:transform-none` cancels the mobile
        // translate so the desktop sidebar never slides.
        "lg:static lg:z-auto lg:w-[232px] lg:max-w-none lg:flex-shrink-0 lg:translate-x-0 lg:transform-none lg:transition-none",
      ].join(" ")}
    >

      {/* Logo */}
      <div className="flex h-[50px] flex-shrink-0 items-center gap-2.5 border-b border-white/5 px-3.5">
        <button
          type="button"
          onClick={() => { onCloseModal(); navigate("/personas") }}
          title="All personas"
          aria-label="Open personas"
          className="flex flex-1 items-center gap-2.5 rounded-md -mx-1 px-1 py-0.5 text-left transition-colors hover:bg-white/5"
        >
          <FoxIcon style={{ fontSize: '17px' }} />
          <span className="flex-1 text-[15px] font-semibold tracking-wide text-white/85">Chatsune</span>
        </button>
        <button
          type="button"
          onClick={() => { if (isDesktop) { toggleCollapsed() } else { useDrawerStore.getState().close() } }}
          title="Collapse sidebar"
          aria-label="Collapse sidebar"
          className="flex h-5 w-5 items-center justify-center rounded text-[13px] text-white/60 transition-colors hover:bg-white/8 hover:text-white/85"
        >
          ⏪
        </button>
      </div>

      {/* Admin banner */}
      {isAdmin && (
        <button
          type="button"
          onClick={() => { closeDrawerIfMobile(); onOpenAdmin() }}
          className={[
            "mx-2 mt-2 flex flex-shrink-0 items-center gap-2 rounded-lg border px-2.5 py-1.5 transition-colors",
            isAdminOpen
              ? "border-gold/30 bg-gold/12"
              : "border-gold/16 bg-gold/7 hover:bg-gold/12",
          ].join(" ")}
        >
          <span className="text-[12px]">🪄</span>
          <span className="flex-1 text-left text-[12px] font-bold uppercase tracking-widest text-gold">Admin</span>
          <span className="text-[11px] text-gold/50">›</span>
        </button>
      )}

      {/* Action block */}
      <ActionBlock
        personas={personas}
        showContinue={!!lastSession && !isInChat}
        onCloseModal={onCloseModal}
        onContinue={handleContinue}
      />

      {/* Entity zones — flex-shared remaining vertical space */}
      <div className="flex min-h-0 flex-1 flex-col">
        <ZoneSection
          zone="personas"
          title="Personas"
          onOpenPage={() => openModalAndClose('personas')}
          itemCount={sortedPersonas.length}
          itemHeight={32}
          emptyState={{
            label: 'No personas yet · Create one →',
            onClick: () => { closeDrawerIfMobile(); onOpenModal('personas') },
          }}
        >
          {(visibleCount) => {
            const visible = sortedPersonas.slice(0, visibleCount)
            const firstUnpinnedIdx = visible.findIndex((p) => !p.pinned)
            const hasPinnedAndUnpinned = firstUnpinnedIdx > 0
            return (
              <>
                {visible.map((p, idx) => (
                  <Fragment key={p.id}>
                    {hasPinnedAndUnpinned && idx === firstUnpinnedIdx && <PinnedDivider />}
                    <PersonaItem
                      persona={p}
                      isActive={p.id === activePersonaId}
                      onSelect={handlePersonaSelect}
                      onNewChat={handleNewChat}
                      onNewIncognitoChat={(persona) => { onCloseModal(); closeDrawerIfMobile(); navigate(`/chat/${persona.id}?incognito=1`) }}
                      onEdit={(persona) => openOverlayAndClose(persona.id, 'edit')}
                      onPin={p.pinned ? undefined : (persona) => onTogglePin?.(persona.id, true)}
                      onUnpin={p.pinned ? (persona) => onTogglePin?.(persona.id, false) : undefined}
                      onOpenOverlay={() => openOverlayAndClose(p.id)}
                    />
                  </Fragment>
                ))}
              </>
            )
          }}
        </ZoneSection>

        {PROJECTS_ENABLED && (
          <ZoneSection
            zone="projects"
            title="Projects"
            onOpenPage={() => openModalAndClose('projects')}
            itemCount={pinnedProjects.length}
            itemHeight={32}
            emptyState={{
              label: 'No pinned projects · Create one →',
              onClick: handleOpenProjectCreateModal,
            }}
          >
            {(visibleCount) => {
              const visible = pinnedProjects.slice(0, visibleCount)
              return (
                <>
                  {visible.map((p) => (
                    <ProjectSidebarItem
                      key={p.id}
                      project={p}
                      onOpen={handleOpenProject}
                      onEdit={handleEditProject}
                      onDelete={handleDeleteProject}
                      onTogglePin={handleToggleProjectPin}
                    />
                  ))}
                </>
              )
            }}
          </ZoneSection>
        )}

        <ZoneSection
          zone="history"
          title="History"
          onOpenPage={() => openModalAndClose('history')}
          itemCount={sortedSessions.length}
          itemHeight={28}
          emptyState={{
            label: 'No conversations yet · Start a new chat →',
            onClick: () => {
              const pick = sortedPersonas[0]
              if (!pick) { navigate('/personas'); return }
              onCloseModal(); closeDrawerIfMobile()
              navigate(`/chat/${pick.id}?new=1`)
            },
          }}
        >
          {(visibleCount) => {
            const visible = sortedSessions.slice(0, visibleCount)
            const firstUnpinnedIdx = visible.findIndex((s) => !s.pinned)
            const hasPinnedAndUnpinned = firstUnpinnedIdx > 0
            return (
              <>
                {visible.map((s, idx) => {
                  const persona = personas.find((p) => p.id === s.persona_id)
                  return (
                    <Fragment key={s.id}>
                      {hasPinnedAndUnpinned && idx === firstUnpinnedIdx && <PinnedDivider />}
                      <HistoryItem
                        session={s}
                        isPinned={s.pinned}
                        isActive={s.id === activeSessionId}
                        monogram={persona?.monogram || persona?.name.charAt(0).toUpperCase()}
                        colourScheme={persona?.colour_scheme}
                        onClick={handleSessionClick}
                        onDelete={handleDeleteSession}
                        onTogglePin={handleToggleSessionPin}
                        onRename={handleRenameSession}
                      />
                    </Fragment>
                  )
                })}
              </>
            )
          }}
        </ZoneSection>
      </div>

      {/* Footer block */}
      <FooterBlock
        avatarTab={avatarTab}
        avatarHighlight={avatarHighlight}
        isSanitised={isSanitised}
        displayName={displayName}
        role={user?.role || ''}
        initial={initial}
        hasApiKeyProblem={hasApiKeyProblem}
        isTabActive={isTabActive}
        onOpenModal={(leaf) => openModalAndClose(leaf)}
        onOpenMyData={handleOpenMyData}
        onToggleSanitised={toggleSanitised}
        onOpenUserRow={() => openModalAndClose(avatarTab)}
        onOpenSettings={() => openModalAndClose('settings')}
        onLogout={() => logout()}
      />

    </aside>
    {projectCreateModal}
    </>
  )
}
