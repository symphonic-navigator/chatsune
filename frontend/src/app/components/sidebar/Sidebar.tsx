import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import {
  DndContext,
  DragOverlay,
  useDroppable,
  useDraggable,
  type DragEndEvent,
  type DragStartEvent,
  pointerWithin,
} from "@dnd-kit/core"
import { SortableContext, verticalListSortingStrategy, useSortable, arrayMove } from "@dnd-kit/sortable"
import { CSS } from "@dnd-kit/utilities"
import { useAuthStore } from "../../../core/store/authStore"
import { useNotificationStore } from "../../../core/store/notificationStore"
import { useSanitisedMode } from "../../../core/store/sanitisedModeStore"
import { useSidebarStore } from "../../../core/store/sidebarStore"
import { hapticLongPress } from "../../../core/utils/haptics"
import { useDrawerStore } from "../../../core/store/drawerStore"
import { useViewport } from "../../../core/hooks/useViewport"
import { useDndSensors } from "../../../core/hooks/useDndSensors"
import { useAuth } from "../../../core/hooks/useAuth"
import { zoomModifiers } from "../../../core/utils/dndZoomModifier"
import { NavRow } from "./NavRow"
import { SidebarFlyout } from './SidebarFlyout'
import { NewChatRow } from './NewChatRow'
import { PersonaItem } from "./PersonaItem"
import { HistoryItem } from "./HistoryItem"
import { MobileSidebarHeader } from './MobileSidebarHeader'
import { MobileMainView } from './MobileMainView'
import { MobileNewChatView } from './MobileNewChatView'
import { HistoryTab } from '../user-modal/HistoryTab'
import { BookmarksTab } from '../user-modal/BookmarksTab'
import type { PersonaDto } from "../../../core/types/persona"
import { chatApi, type ChatSessionDto } from "../../../core/api/chat"
import type { TopTabId, SubTabId } from "../user-modal/userModalTree"
import { safeLocalStorage } from "../../../core/utils/safeStorage"

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
  onReorder?: (orderedIds: string[]) => void
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

function DroppableZone({ id, children }: { id: string; children: React.ReactNode }) {
  const { setNodeRef, isOver } = useDroppable({ id })
  return (
    <div ref={setNodeRef} className={`transition-colors rounded-md ${isOver ? "bg-white/4" : ""}`}>
      {children}
    </div>
  )
}

function SortablePersonaItem({
  persona,
  ...rest
}: Omit<React.ComponentProps<typeof PersonaItem>, "dragRef" | "dragListeners" | "dragAttributes" | "isDragging">) {
  const { attributes, listeners, setNodeRef, isDragging, transform, transition } = useSortable({ id: persona.id })
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  }
  return (
    <div style={style}>
      <PersonaItem
        persona={persona}
        dragRef={setNodeRef}
        dragListeners={listeners}
        dragAttributes={attributes}
        isDragging={isDragging}
        {...rest}
      />
    </div>
  )
}

function DraggableHistoryItem({
  session,
  ...rest
}: Omit<React.ComponentProps<typeof HistoryItem>, "dragListeners" | "dragAttributes" | "isDragging">) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: `session:${session.id}` })
  return (
    <div ref={setNodeRef}>
      <HistoryItem
        session={session}
        dragListeners={listeners}
        dragAttributes={attributes}
        isDragging={isDragging}
        {...rest}
      />
    </div>
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
  onReorder,
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

  const [historyOpen, setHistoryOpen] = useState(() => {
    const stored = safeLocalStorage.getItem("chatsune_history_open")
    return stored === null ? true : stored === "true"
  })

  function toggleHistory() {
    const next = !historyOpen
    setHistoryOpen(next)
    safeLocalStorage.setItem("chatsune_history_open", String(next))
  }

  const hasPinnedPersonas = personas.some((p) => p.pinned)
  const hasExplicitUnpinnedPref = safeLocalStorage.hasItem("chatsune_unpinned_open")
  const [unpinnedOpen, setUnpinnedOpen] = useState(() => {
    if (hasExplicitUnpinnedPref) {
      return safeLocalStorage.getItem("chatsune_unpinned_open") === "true"
    }
    // Default open when no personas are pinned so users can see their personas
    return !hasPinnedPersonas
  })

  // Auto-open the unpinned section when no personas are pinned
  useEffect(() => {
    if (!hasPinnedPersonas) {
      setUnpinnedOpen(true)
    }
  }, [hasPinnedPersonas])

  function toggleUnpinned() {
    const next = !unpinnedOpen
    setUnpinnedOpen(next)
    safeLocalStorage.setItem("chatsune_unpinned_open", String(next))
  }

  const [historySearch, setHistorySearch] = useState("")

  // Projects flyout is hidden (see FOR_LATER.md), so the flyout tab type is
  // currently history-only. Keep the union shape so re-enabling Projects later
  // is a one-line widening rather than reshaping every callsite.
  const [flyoutTab, setFlyoutTab] = useState<'history' | null>(null)

  type MobileView = 'main' | 'new-chat' | 'history' | 'bookmarks'
  const [mobileView, setMobileView] = useState<MobileView>('main')

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

  const [dragActiveId, setDragActiveId] = useState<string | null>(null)
  const [historyDragActiveId, setHistoryDragActiveId] = useState<string | null>(null)

  const pinnedPersonas = personas.filter((p) => p.pinned)
  const unpinnedPersonas = personas.filter((p) => !p.pinned)
  const pinnedIds = pinnedPersonas.map((p) => p.id)
  const unpinnedIds = unpinnedPersonas.map((p) => p.id)
  const dragActivePersona = dragActiveId ? personas.find((p) => p.id === dragActiveId) ?? null : null

  function findZone(id: string): "pinned" | "unpinned" | null {
    if (id === "pinned-zone") return "pinned"
    if (id === "unpinned-zone") return "unpinned"
    if (pinnedPersonas.some((p) => p.id === id)) return "pinned"
    if (unpinnedPersonas.some((p) => p.id === id)) return "unpinned"
    return null
  }

  const dndSensors = useDndSensors()

  function handleDragStart(event: DragStartEvent) {
    hapticLongPress()
    setDragActiveId(event.active.id as string)
  }

  function handleDragEnd(event: DragEndEvent) {
    setDragActiveId(null)
    const { active, over } = event
    if (!over) return

    const activeId = active.id as string
    const overId = over.id as string
    const persona = personas.find((p) => p.id === activeId)
    if (!persona) return

    const fromZone = findZone(activeId)
    const toZone = findZone(overId)
    if (!fromZone || !toZone) return

    if (fromZone === toZone && activeId !== overId) {
      // Reorder within the same zone
      const list = fromZone === "pinned" ? [...pinnedIds] : [...unpinnedIds]
      const oldIndex = list.indexOf(activeId)
      const newIndex = list.indexOf(overId)
      if (oldIndex === -1 || newIndex === -1) return
      const reordered = arrayMove(list, oldIndex, newIndex)
      // Combine: reordered zone first (pinned), then the other zone
      const fullOrder = fromZone === "pinned"
        ? [...reordered, ...unpinnedIds]
        : [...pinnedIds, ...reordered]
      onReorder?.(fullOrder)
    } else if (fromZone !== toZone) {
      // Move between zones — toggle pin status and insert at drop position
      const newPinned = toZone === "pinned"
      onTogglePin?.(activeId, newPinned)

      const targetList = toZone === "pinned" ? [...pinnedIds] : [...unpinnedIds]
      const dropIndex = targetList.indexOf(overId)
      if (dropIndex !== -1) {
        targetList.splice(dropIndex, 0, activeId)
      } else {
        targetList.push(activeId)
      }
      const sourceList = fromZone === "pinned"
        ? pinnedIds.filter((id) => id !== activeId)
        : unpinnedIds.filter((id) => id !== activeId)

      const fullOrder = toZone === "pinned"
        ? [...targetList, ...sourceList]
        : [...sourceList, ...targetList]
      onReorder?.(fullOrder)
    }
  }

  // On mobile the sidebar lives in an off-canvas drawer; once the user has
  // picked something, collapse it automatically so the chat is visible.
  // Desktop keeps the sidebar open — there is enough room for both.
  function closeDrawerIfMobile() {
    if (!isDesktop) {
      useDrawerStore.getState().close()
    }
  }

  /** Close any mobile overlay AND the drawer itself. Used by item-tap in
   *  History/Bookmarks/New-Chat to fully collapse. */
  function closeOverlayAndDrawer() {
    setMobileView('main')
    if (!isDesktop) {
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

  function handlePersonaSelect(persona: PersonaDto) {
    onCloseModal()
    closeDrawerIfMobile()
    navigate(`/chat/${persona.id}`)
  }

  function handleNewChat(persona: PersonaDto) {
    onCloseModal()
    closeDrawerIfMobile()
    navigate(`/chat/${persona.id}?new=1`)
  }

  function handleNewChatFromMobileOverlay(persona: PersonaDto) {
    onCloseModal()
    setMobileView('main')
    useDrawerStore.getState().close()
    navigate(`/chat/${persona.id}?new=1`)
  }

  function handleSessionClick(session: ChatSessionDto) {
    onCloseModal()
    closeDrawerIfMobile()
    navigate(`/chat/${session.persona_id}/${session.id}`)
  }

  function handleContinue() {
    if (!lastSession) return
    onCloseModal()
    closeDrawerIfMobile()
    navigate(`/chat/${lastSession.persona_id}/${lastSession.id}`)
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

  function handleHistoryDragStart(event: DragStartEvent) {
    hapticLongPress()
    setHistoryDragActiveId(event.active.id as string)
  }

  function handleHistoryDragEnd(event: DragEndEvent) {
    setHistoryDragActiveId(null)
    const { active, over } = event
    if (!over) return

    const activeId = (active.id as string).replace("session:", "")
    const overId = over.id as string

    // Determine which zone it was dropped into
    const session = sessions.find((s) => s.id === activeId)
    if (!session) return

    if (overId === "pinned-sessions-zone" && !session.pinned) {
      onToggleSessionPin?.(activeId, true)
    } else if (overId === "unpinned-sessions-zone" && session.pinned) {
      onToggleSessionPin?.(activeId, false)
    }
    // If dropped on another session item, check which zone that item belongs to
    else if (overId.startsWith("session:")) {
      const targetId = overId.replace("session:", "")
      const targetSession = sessions.find((s) => s.id === targetId)
      if (targetSession) {
        const targetPinned = targetSession.pinned
        if (session.pinned !== targetPinned) {
          onToggleSessionPin?.(activeId, targetPinned)
        }
      }
    }
  }

  const historyDragActiveSession = historyDragActiveId
    ? sessions.find((s) => s.id === historyDragActiveId.replace("session:", ""))
    : null

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

  // ── Collapsed view ──────────────────────────────────────────────
  if (renderCollapsed) {
    return (
      <aside className="flex h-full w-[50px] flex-shrink-0 flex-col items-center border-r border-white/6 bg-base py-2 gap-0.5">
        {/* Logo — expand */}
        <button
          type="button"
          onClick={() => { setFlyoutTab(null); setHistorySearch(""); toggleCollapsed() }}
          title="Expand sidebar"
          aria-label="Expand sidebar"
          className="group flex h-[34px] w-[34px] items-center justify-center rounded-lg text-[17px] transition-colors hover:bg-white/8"
        >
          <span className="group-hover:hidden">🦊</span>
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
          icon="🎓"
          onClick={() => onOpenModal('knowledge')}
          title="Knowledge"
          isActive={isTabActive('knowledge')}
        />

        {/* Bookmarks */}
        <IconBtn
          icon="🔖"
          onClick={() => onOpenModal('bookmarks')}
          title="Bookmarks"
          isActive={isTabActive('bookmarks')}
        />

        {/* Uploads */}
        <IconBtn
          icon="📂"
          onClick={() => onOpenModal('uploads')}
          title="Uploads"
          isActive={isTabActive('uploads')}
        />

        {/* Artefacts */}
        <IconBtn
          icon="🧪"
          onClick={() => onOpenModal('artefacts')}
          title="Artefacts"
          isActive={isTabActive('artefacts')}
        />

        {/* Images */}
        <IconBtn
          icon="🖼️"
          onClick={() => onOpenModal('images')}
          title="Images"
          isActive={isTabActive('images')}
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
          <span className={isSanitised ? "opacity-100" : "opacity-60 grayscale"}>🔒</span>
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
    )
  }

  // ── Mobile branch ───────────────────────────────────────────────────
  if (!isDesktop) {
    const handleAdmin     = () => { closeDrawerIfMobile(); onOpenAdmin() }
    const handlePersonas  = () => { onCloseModal(); closeDrawerIfMobile(); navigate('/personas') }
    const handleKnowledge = () => openModalAndClose('knowledge')
    const handleMyData    = () => openModalAndClose('my-data')
    const handleUserRow   = () => openModalAndClose(avatarTab)
    const handleClose     = () => useDrawerStore.getState().close()

    const overlayTitle =
      mobileView === 'new-chat'  ? 'New Chat'  :
      mobileView === 'history'   ? 'History'   :
      mobileView === 'bookmarks' ? 'Bookmarks' :
      undefined

    return (
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
                displayName={displayName}
                role={user?.role || ''}
                initial={initial}
                onAdmin={handleAdmin}
                onContinue={handleContinue}
                onNewChat={() => setMobileView('new-chat')}
                onPersonas={handlePersonas}
                onHistory={() => setMobileView('history')}
                onBookmarks={() => setMobileView('bookmarks')}
                onKnowledge={handleKnowledge}
                onMyData={handleMyData}
                onToggleSanitised={toggleSanitised}
                onUserRow={handleUserRow}
                onLogout={() => logout()}
              />
            </div>

            <div className="h-full w-1/2 flex-shrink-0 overflow-hidden">
              {mobileView === 'new-chat'  && <MobileNewChatView personas={personas} onSelect={handleNewChatFromMobileOverlay} onClose={closeOverlayAndDrawer} />}
              {mobileView === 'history'   && <HistoryTab   onClose={closeOverlayAndDrawer} />}
              {mobileView === 'bookmarks' && <BookmarksTab onClose={closeOverlayAndDrawer} />}
            </div>
          </div>
        </div>
      </aside>
    )
  }

  // ── Desktop expanded view ──────────────────────────────────────────────
  return (
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
          <span className="text-[17px]">🦊</span>
          <span className="flex-1 text-[15px] font-semibold tracking-wide text-white/85">Chatsune</span>
        </button>
        <button
          type="button"
          onClick={() => { setHistorySearch(""); if (isDesktop) { toggleCollapsed() } else { useDrawerStore.getState().close() } }}
          title="Collapse sidebar"
          aria-label="Collapse sidebar"
          className="flex h-5 w-5 items-center justify-center rounded text-[13px] text-white/60 transition-colors hover:bg-white/8 hover:text-white/85"
        >
          ⏪
        </button>
      </div>

      {/* Scrollable middle zone: personas, projects, history.
          This is the only scrollable region — the bottom nav stays pinned
          on both mobile and desktop. */}
      <div className="min-h-0 flex-1 overflow-y-auto [&::-webkit-scrollbar]:w-[3px] [&::-webkit-scrollbar-thumb]:rounded-sm [&::-webkit-scrollbar-thumb]:bg-white/10">

      {/* Admin banner */}
      {isAdmin && (
        <button
          type="button"
          onClick={() => { closeDrawerIfMobile(); onOpenAdmin() }}
          className={[
            "mx-2 mt-2 flex items-center gap-2 rounded-lg border px-2.5 py-1.5 transition-colors",
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

      {/* New Chat */}
      <NewChatRow personas={personas} onCloseModal={onCloseModal} />

      {/* PERSONAS */}
      <div className="mt-1.5">
        <NavRow icon="💞" label="Personas" onClick={() => { onCloseModal(); navigate("/personas") }} />

        {/* Continue last session */}
        {lastSession && !isInChat && (
          <button
            type="button"
            onClick={handleContinue}
            className="group mx-3 mb-0.5 flex w-[calc(100%-24px)] items-center gap-2 rounded-md px-2 py-1 text-left transition-colors hover:bg-white/5"
          >
            <span className="text-[10px] text-white/60 group-hover:text-white/80">▶️</span>
            <span className="text-[12px] text-white/60 group-hover:text-white/85">Continue</span>
          </button>
        )}

        <DndContext
          sensors={dndSensors}
          collisionDetection={pointerWithin}
          onDragStart={handleDragStart}
          onDragEnd={handleDragEnd}
        >
          {/* Pinned personas */}
          <DroppableZone id="pinned-zone">
            <SortableContext items={pinnedIds} strategy={verticalListSortingStrategy}>
              <div className="mt-0.5 min-h-[8px]">
                {pinnedPersonas.length > 0 ? pinnedPersonas.map((p) => (
                  <SortablePersonaItem
                    key={p.id}
                    persona={p}
                    isActive={p.id === activePersonaId}
                    onSelect={handlePersonaSelect}
                    onNewChat={handleNewChat}
                    onNewIncognitoChat={(persona) => { onCloseModal(); closeDrawerIfMobile(); navigate(`/chat/${persona.id}?incognito=1`) }}
                    onEdit={(persona) => openOverlayAndClose(persona.id, 'edit')}
                    onUnpin={(persona) => onTogglePin?.(persona.id, false)}
                    onOpenOverlay={() => openOverlayAndClose(p.id)}
                  />
                )) : (
                  <p className="px-4 py-1 text-[12px] text-white/50">No pinned personas</p>
                )}
              </div>
            </SortableContext>
          </DroppableZone>

          {/* Other personas */}
          {unpinnedPersonas.length > 0 && (
            <>
              <button
                type="button"
                onClick={toggleUnpinned}
                className="mx-2 mt-1 flex w-[calc(100%-16px)] items-center gap-1.5 rounded-md px-2 py-1 text-left transition-colors hover:bg-white/5"
              >
                <span className="text-[10px] text-white/60">{unpinnedOpen ? "∨" : "›"}</span>
                <span className="text-[11px] font-medium uppercase tracking-wider text-white/60">Other Personas</span>
                <span className="text-[10px] text-white/60">{unpinnedPersonas.length}</span>
              </button>
              {unpinnedOpen && (
                <DroppableZone id="unpinned-zone">
                  <SortableContext items={unpinnedIds} strategy={verticalListSortingStrategy}>
                    <div className="mt-0.5 min-h-[8px]">
                      {unpinnedPersonas.map((p) => (
                        <SortablePersonaItem
                          key={p.id}
                          persona={p}
                          isActive={p.id === activePersonaId}
                          onSelect={handlePersonaSelect}
                          onNewChat={handleNewChat}
                          onNewIncognitoChat={(persona) => { onCloseModal(); closeDrawerIfMobile(); navigate(`/chat/${persona.id}?incognito=1`) }}
                          onEdit={(persona) => openOverlayAndClose(persona.id, 'edit')}
                          onPin={(persona) => onTogglePin?.(persona.id, true)}
                          onOpenOverlay={() => openOverlayAndClose(p.id)}
                        />
                      ))}
                    </div>
                  </SortableContext>
                </DroppableZone>
              )}
            </>
          )}

          {/* Drag overlay */}
          <DragOverlay modifiers={zoomModifiers}>
            {dragActivePersona ? (
              <div className="rounded-lg border border-white/10 bg-elevated px-3 py-1.5 text-[13px] text-white/70 shadow-xl">
                {dragActivePersona.name}
              </div>
            ) : null}
          </DragOverlay>
        </DndContext>

      <div className="mx-2 my-1.5 h-px bg-white/4" />

        {/* Projects desktop NavRow hidden — feature not yet ready (see FOR_LATER.md) */}

        <div className="mx-2 my-1 h-px bg-white/4" />

        {/* HISTORY */}
        <NavRow
          icon="📖"
          label="History"
          isActive={isTabActive('history')}
          onClick={() => openModalAndClose('history')}
          actions={
            <>
              <button
                type="button"
                className="flex h-[22px] w-[22px] items-center justify-center rounded text-[11px] text-white/60 transition-colors hover:bg-white/8 hover:text-white/85"
                onClick={(e) => { e.stopPropagation(); toggleHistory() }}
                aria-label={historyOpen ? "Collapse history" : "Expand history"}
                title={historyOpen ? "Collapse history" : "Expand history"}
              >
                {historyOpen ? "∨" : "›"}
              </button>
            </>
          }
        />

        {historyOpen && (
          <>
            {sessions.length > 0 && (
              <div className="mx-2 mt-0.5 mb-1">
                <input
                  type="text"
                  value={historySearch}
                  onChange={(e) => setHistorySearch(e.target.value)}
                  placeholder="Filter sessions..."
                  className="w-full rounded-md border border-white/6 bg-white/4 px-2 py-1 text-[11px] text-white/70 placeholder-white/55 outline-none transition-colors focus:border-white/12 focus:bg-white/6"
                />
              </div>
            )}

            <DndContext
              sensors={dndSensors}
              collisionDetection={pointerWithin}
              onDragStart={handleHistoryDragStart}
              onDragEnd={handleHistoryDragEnd}
            >
              <div className="mt-0.5 pb-2">
                {/* Pinned sessions */}
                <DroppableZone id="pinned-sessions-zone">
                  <div className="min-h-[4px]">
                    {pinnedSessions.map((s) => {
                      const persona = personas.find((p) => p.id === s.persona_id)
                      return (
                        <DraggableHistoryItem
                          key={s.id}
                          session={s}
                          isPinned={true}
                          isActive={s.id === activeSessionId}
                          monogram={persona?.monogram || persona?.name.charAt(0).toUpperCase()}
                          colourScheme={persona?.colour_scheme}
                          onClick={handleSessionClick}
                          onDelete={handleDeleteSession}
                          onTogglePin={handleToggleSessionPin}
                        />
                      )
                    })}
                  </div>
                </DroppableZone>

                {pinnedSessions.length > 0 && <div className="mx-3 my-1 h-px bg-white/4" />}

                {/* Unpinned sessions */}
                <DroppableZone id="unpinned-sessions-zone">
                  <div className="min-h-[4px]">
                    {unpinnedSessions.slice(0, 8).map((s) => {
                      const persona = personas.find((p) => p.id === s.persona_id)
                      return (
                        <DraggableHistoryItem
                          key={s.id}
                          session={s}
                          isPinned={false}
                          isActive={s.id === activeSessionId}
                          monogram={persona?.monogram || persona?.name.charAt(0).toUpperCase()}
                          colourScheme={persona?.colour_scheme}
                          onClick={handleSessionClick}
                          onDelete={handleDeleteSession}
                          onTogglePin={handleToggleSessionPin}
                        />
                      )
                    })}
                  </div>
                </DroppableZone>

                {unpinnedSessions.length > 8 && (
                  <button
                    type="button"
                    onClick={() => openModalAndClose('history')}
                    className="mx-3 mt-1 flex w-[calc(100%-24px)] items-center gap-1.5 rounded-md px-2 py-1 text-[11px] text-white/40 transition-colors hover:bg-white/5 hover:text-white/60"
                  >
                    <span>+{unpinnedSessions.length - 8} more</span>
                  </button>
                )}

                {sessions.length === 0 && (
                  <p className="px-4 py-1 text-[12px] text-white/50">No history yet</p>
                )}
                {sessions.length > 0 && pinnedSessions.length === 0 && unpinnedSessions.length === 0 && (
                  <p className="px-4 py-1 text-[12px] text-white/60">No matching sessions</p>
                )}
              </div>

              {/* History drag overlay */}
              <DragOverlay modifiers={zoomModifiers}>
                {historyDragActiveSession ? (
                  <div className="rounded-lg border border-white/10 bg-elevated px-3 py-1.5 text-[13px] text-white/70 shadow-xl">
                    {historyDragActiveSession.title ?? 'Untitled session'}
                  </div>
                ) : null}
              </DragOverlay>
            </DndContext>
          </>
        )}

      </div>

      </div>{/* end scroll container */}

      {/* Bottom — pinned on desktop, scrolls with content on mobile */}
      <div className="flex-shrink-0 border-t border-white/5">
        {/* Knowledge */}
        <NavRow
          icon="🎓"
          label="Knowledge"
          isActive={isTabActive('knowledge')}
          onClick={() => openModalAndClose('knowledge')}
        />

        {/* Bookmarks */}
        <NavRow
          icon="🔖"
          label="Bookmarks"
          isActive={isTabActive('bookmarks')}
          onClick={() => openModalAndClose('bookmarks')}
        />

        {/* Uploads */}
        <NavRow
          icon="📂"
          label="Uploads"
          isActive={isTabActive('uploads')}
          onClick={() => openModalAndClose('uploads')}
        />

        {/* Artefacts */}
        <NavRow
          icon="🧪"
          label="Artefacts"
          isActive={isTabActive('artefacts')}
          onClick={() => openModalAndClose('artefacts')}
        />

        {/* Images gallery */}
        <NavRow
          icon="🖼️"
          label="Images"
          isActive={isTabActive('images')}
          onClick={() => openModalAndClose('images')}
        />

        <div className="mx-2 my-1.5 h-px bg-white/4" />

        {/* Sanitised mode toggle */}
        <button
          type="button"
          onClick={toggleSanitised}
          title={isSanitised ? "Sanitised mode on — NSFW content hidden" : "Sanitised mode off — all content visible"}
          aria-label={isSanitised ? "Turn sanitised mode off" : "Turn sanitised mode on"}
          aria-pressed={isSanitised}
          className="flex w-full items-center gap-2.5 px-3.5 py-1.5 transition-colors hover:bg-white/5"
        >
          <span className={`text-[15px] ${isSanitised ? "opacity-100" : "opacity-60 grayscale"}`}>
            🔒
          </span>
          <span className={`text-[13px] transition-colors ${isSanitised ? "text-gold font-medium" : "text-white/60"}`}>
            Sanitised
          </span>
        </button>

        <div className="mx-2 my-1.5 h-px bg-white/4" />

        {/* User row */}
        <div
          className={[
            "flex items-center gap-2.5 px-3 py-2 transition-colors",
            avatarHighlight ? "bg-gold/7" : "",
          ].join(" ")}
        >
          <button
            type="button"
            onClick={() => openModalAndClose(avatarTab)}
            className="flex flex-1 items-center gap-2.5 min-w-0 hover:opacity-80 transition-opacity"
            title="Your profile"
          >
            <div className="relative flex h-[30px] w-[30px] flex-shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-purple to-gold text-[12px] font-bold text-white">
              {initial}
              {hasApiKeyProblem && (
                <span className="absolute -top-0.5 -right-0.5 flex h-3 w-3 items-center justify-center rounded-full bg-red-500 text-[7px] font-bold text-white">!</span>
              )}
            </div>
            <div className="text-left min-w-0">
              <p className={[
                "text-[13px] font-medium truncate transition-colors",
                avatarHighlight ? "text-gold" : "text-white/65",
              ].join(" ")}>
                {displayName}
              </p>
              <p className="text-[10px] text-white/60">{user?.role}</p>
            </div>
          </button>

          {/* Settings shortcut */}
          <button
            type="button"
            onClick={() => openModalAndClose('settings')}
            title="Settings"
            aria-label="Settings"
            className="flex h-[22px] w-[22px] flex-shrink-0 items-center justify-center rounded text-[11px] text-white/60 transition-colors hover:bg-white/8 hover:text-white/85"
          >
            ···
          </button>
        </div>

        {/* Logout */}
        <button
          type="button"
          onClick={() => logout()}
          aria-label="Log out"
          className="flex w-full items-center gap-2 px-4 py-1.5 text-[11px] text-white/60 hover:text-white/85 transition-colors font-mono"
        >
          <span>↪</span>
          <span>Log out</span>
        </button>
      </div>

    </aside>
  )
}
