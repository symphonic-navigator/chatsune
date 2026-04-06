import { useState } from "react"
import { useNavigate } from "react-router-dom"
import {
  DndContext,
  DragOverlay,
  closestCenter,
  useDroppable,
  useDraggable,
  type DragEndEvent,
  type DragStartEvent,
  type DragOverEvent,
  pointerWithin,
} from "@dnd-kit/core"
import { SortableContext, verticalListSortingStrategy, useSortable, arrayMove } from "@dnd-kit/sortable"
import { CSS } from "@dnd-kit/utilities"
import { useAuthStore } from "../../../core/store/authStore"
import { useSanitisedMode } from "../../../core/store/sanitisedModeStore"
import { useSidebarStore } from "../../../core/store/sidebarStore"
import { useAuth } from "../../../core/hooks/useAuth"
import { NavRow } from "./NavRow"
import { PersonaItem } from "./PersonaItem"
import { HistoryItem } from "./HistoryItem"
import type { PersonaDto } from "../../../core/types/persona"
import { chatApi, type ChatSessionDto } from "../../../core/api/chat"
import type { UserModalTab } from "../user-modal/UserModal"

interface SidebarProps {
  personas: PersonaDto[]
  sessions: ChatSessionDto[]
  activePersonaId: string | null
  activeSessionId: string | null
  onOpenModal: (tab: UserModalTab) => void
  onCloseModal: () => void
  activeModalTab: UserModalTab | null
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
      className={[
        "flex h-8 w-8 items-center justify-center rounded-lg text-sm transition-colors hover:bg-white/8",
        isActive ? "text-gold" : "text-white/50",
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
  activeModalTab,
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
  const { logout } = useAuth()
  const navigate = useNavigate()

  const isAdmin = user?.role === "admin" || user?.role === "master_admin"
  const isInChat = !!activePersonaId
  const lastSession = sessions[0] ?? null

  const [projectsOpen, setProjectsOpen] = useState(() => {
    return localStorage.getItem("chatsune_projects_open") === "true"
  })

  function toggleProjects() {
    const next = !projectsOpen
    setProjectsOpen(next)
    localStorage.setItem("chatsune_projects_open", String(next))
  }

  const [unpinnedOpen, setUnpinnedOpen] = useState(() => {
    return localStorage.getItem("chatsune_unpinned_open") === "true"
  })

  function toggleUnpinned() {
    const next = !unpinnedOpen
    setUnpinnedOpen(next)
    localStorage.setItem("chatsune_unpinned_open", String(next))
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

  function handleDragStart(event: DragStartEvent) {
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

  function handlePersonaSelect(persona: PersonaDto) {
    onCloseModal()
    navigate(`/chat/${persona.id}`)
  }

  function handleNewChat(persona: PersonaDto) {
    onCloseModal()
    navigate(`/chat/${persona.id}?new=1`)
  }

  function handleSessionClick(session: ChatSessionDto) {
    onCloseModal()
    navigate(`/chat/${session.persona_id}/${session.id}`)
  }

  function handleContinue() {
    if (!lastSession) return
    onCloseModal()
    navigate(`/chat/${lastSession.persona_id}/${lastSession.id}`)
  }

  const pinnedSessions = sessions.filter((s) => s.pinned)
  const unpinnedSessions = sessions.filter((s) => !s.pinned)

  function handleToggleSessionPin(session: ChatSessionDto, pinned: boolean) {
    onToggleSessionPin?.(session.id, pinned)
  }

  function handleHistoryDragStart(event: DragStartEvent) {
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
    } catch {
      // Event-driven removal handles the UI update; error is non-critical
    }
  }

  const isTabActive = (tab: UserModalTab) => activeModalTab === tab

  const avatarTab: UserModalTab = hasApiKeyProblem ? 'api-keys' : 'about-me'

  const avatarHighlight =
    activeModalTab === 'about-me' || activeModalTab === 'settings' || activeModalTab === 'api-keys'

  const displayName = user?.display_name || user?.username || 'Unnamed User'
  const initial = displayName.charAt(0).toUpperCase()

  // ── Collapsed view ──────────────────────────────────────────────
  if (isCollapsed) {
    return (
      <aside className="flex h-full w-[50px] flex-shrink-0 flex-col items-center border-r border-white/6 bg-base py-2 gap-0.5">
        {/* Logo — expand */}
        <button
          type="button"
          onClick={toggleCollapsed}
          title="Expand sidebar"
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

        {/* Projects */}
        <IconBtn
          icon="🔭"
          onClick={() => onOpenModal('projects')}
          title="Projects"
          isActive={isTabActive('projects')}
        />

        {/* History */}
        <IconBtn
          icon="📖"
          onClick={() => onOpenModal('history')}
          title="History"
          isActive={isTabActive('history')}
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

        <div className="mx-auto my-1 h-px w-6 bg-white/4" />

        {/* Sanitised */}
        <button
          type="button"
          onClick={toggleSanitised}
          title={isSanitised ? "Sanitised mode on" : "Sanitised mode off"}
          className="flex h-8 w-8 items-center justify-center rounded-lg text-sm transition-colors hover:bg-white/8"
        >
          <span className={isSanitised ? "opacity-100" : "opacity-25 grayscale"}>🔒</span>
        </button>

        <div className="mx-auto my-1 h-px w-6 bg-white/4" />

        {/* User avatar */}
        <button
          type="button"
          onClick={() => onOpenModal(avatarTab)}
          title={displayName}
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
          className="flex h-8 w-8 items-center justify-center rounded-lg text-[11px] text-white/30 transition-colors hover:bg-white/8 hover:text-white/55"
        >
          ↪
        </button>
      </aside>
    )
  }

  // ── Expanded view ───────────────────��─────────────────────��─────
  return (
    <aside className="flex h-full w-[232px] flex-shrink-0 flex-col border-r border-white/6 bg-base">

      {/* Logo */}
      <div className="flex h-[50px] flex-shrink-0 items-center gap-2.5 border-b border-white/5 px-3.5">
        <span className="text-[17px]">🦊</span>
        <span className="flex-1 text-[15px] font-semibold tracking-wide text-white/85">Chatsune</span>
        <button
          type="button"
          onClick={toggleCollapsed}
          title="Collapse sidebar"
          className="flex h-5 w-5 items-center justify-center rounded text-[13px] text-white/25 transition-colors hover:bg-white/8 hover:text-white/55"
        >
          ⏪
        </button>
      </div>

      {/* Admin banner */}
      {isAdmin && (
        <button
          type="button"
          onClick={onOpenAdmin}
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

      {/* PERSONAS */}
      <div className="mt-1.5 flex-shrink-0">
        <NavRow icon="💞" label="Personas" onClick={() => { onCloseModal(); navigate("/personas") }} />

        {/* Continue last session */}
        {lastSession && !isInChat && (
          <button
            type="button"
            onClick={handleContinue}
            className="group mx-3 mb-0.5 flex w-[calc(100%-24px)] items-center gap-2 rounded-md px-2 py-1 text-left transition-colors hover:bg-white/5"
          >
            <span className="text-[10px] text-white/25 group-hover:text-white/50">▶️</span>
            <span className="text-[12px] text-white/35 group-hover:text-white/60">Continue</span>
          </button>
        )}

        <DndContext
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
                    onNewIncognitoChat={(persona) => { onCloseModal(); navigate(`/chat/${persona.id}?incognito=1`) }}
                    onEdit={(persona) => onOpenOverlay?.(persona.id, 'edit')}
                    onUnpin={(persona) => onTogglePin?.(persona.id, false)}
                    onOpenOverlay={() => onOpenOverlay?.(p.id)}
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
                <span className="text-[10px] text-white/30">{unpinnedOpen ? "∨" : "›"}</span>
                <span className="text-[11px] font-medium uppercase tracking-wider text-white/30">Other Personas</span>
                <span className="text-[10px] text-white/20">{unpinnedPersonas.length}</span>
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
                          onNewIncognitoChat={(persona) => { onCloseModal(); navigate(`/chat/${persona.id}?incognito=1`) }}
                          onEdit={(persona) => onOpenOverlay?.(persona.id, 'edit')}
                          onPin={(persona) => onTogglePin?.(persona.id, true)}
                          onOpenOverlay={() => onOpenOverlay?.(p.id)}
                        />
                      ))}
                    </div>
                  </SortableContext>
                </DroppableZone>
              )}
            </>
          )}

          {/* Drag overlay */}
          <DragOverlay>
            {dragActivePersona ? (
              <div className="rounded-lg border border-white/10 bg-elevated px-3 py-1.5 text-[13px] text-white/70 shadow-xl">
                {dragActivePersona.name}
              </div>
            ) : null}
          </DragOverlay>
        </DndContext>
      </div>

      <div className="mx-2 my-1.5 h-px bg-white/4" />

      {/* Shared scroll zone: Projects + History */}
      <div className="min-h-0 flex-1 overflow-y-auto [&::-webkit-scrollbar]:w-[3px] [&::-webkit-scrollbar-thumb]:rounded-sm [&::-webkit-scrollbar-thumb]:bg-white/10">

        {/* PROJECTS */}
        <NavRow
          icon="🔭"
          label="Projects"
          isActive={isTabActive('projects')}
          onClick={() => onOpenModal('projects')}
          actions={
            <>
              <button
                type="button"
                className="flex h-[22px] w-[22px] items-center justify-center rounded text-[11px] text-white/30 transition-colors hover:bg-white/8 hover:text-white/65"
                onClick={(e) => { e.stopPropagation(); toggleProjects() }}
                aria-label={projectsOpen ? "Collapse projects" : "Expand projects"}
              >
                {projectsOpen ? "∨" : "›"}
              </button>
            </>
          }
        />

        {projectsOpen && (
          <p className="mx-3 py-1 text-[12px] text-white/50">No projects yet</p>
        )}

        <div className="mx-2 my-1 h-px bg-white/4" />

        {/* HISTORY */}
        <NavRow
          icon="📖"
          label="History"
          isActive={isTabActive('history')}
          onClick={() => onOpenModal('history')}
          actions={null}
        />

        <DndContext
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
                {unpinnedSessions.map((s) => {
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

            {sessions.length === 0 && (
              <p className="px-4 py-1 text-[12px] text-white/50">No history yet</p>
            )}
          </div>

          {/* History drag overlay */}
          <DragOverlay>
            {historyDragActiveSession ? (
              <div className="rounded-lg border border-white/10 bg-elevated px-3 py-1.5 text-[13px] text-white/70 shadow-xl">
                {historyDragActiveSession.title ?? 'Untitled session'}
              </div>
            ) : null}
          </DragOverlay>
        </DndContext>

      </div>

      {/* Bottom */}
      <div className="flex-shrink-0 border-t border-white/5">
        {/* Knowledge */}
        <NavRow
          icon="🎓"
          label="Knowledge"
          isActive={isTabActive('knowledge')}
          onClick={() => onOpenModal('knowledge')}
        />

        {/* Bookmarks */}
        <NavRow
          icon="🔖"
          label="Bookmarks"
          isActive={isTabActive('bookmarks')}
          onClick={() => onOpenModal('bookmarks')}
        />

        {/* Uploads */}
        <NavRow
          icon="📂"
          label="Uploads"
          isActive={isTabActive('uploads')}
          onClick={() => onOpenModal('uploads')}
        />

        {/* Artefacts */}
        <NavRow
          icon="🧪"
          label="Artefacts"
          isActive={isTabActive('artefacts')}
          onClick={() => onOpenModal('artefacts')}
        />

        <div className="mx-2 my-1.5 h-px bg-white/4" />

        {/* Sanitised mode toggle */}
        <button
          type="button"
          onClick={toggleSanitised}
          title={isSanitised ? "Sanitised mode on — NSFW content hidden" : "Sanitised mode off — all content visible"}
          className="flex w-full items-center gap-2.5 px-3.5 py-1.5 transition-colors hover:bg-white/5"
        >
          <span className={`text-[15px] ${isSanitised ? "opacity-100" : "opacity-25 grayscale"}`}>
            🔒
          </span>
          <span className={`text-[13px] transition-colors ${isSanitised ? "text-gold font-medium" : "text-white/30"}`}>
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
            onClick={() => onOpenModal(avatarTab)}
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
              <p className="text-[10px] text-white/30">{user?.role}</p>
            </div>
          </button>

          {/* Settings shortcut */}
          <button
            type="button"
            onClick={() => onOpenModal('settings')}
            title="Settings"
            className="flex h-[22px] w-[22px] flex-shrink-0 items-center justify-center rounded text-[11px] text-white/30 transition-colors hover:bg-white/8 hover:text-white/65"
          >
            ···
          </button>
        </div>

        {/* Logout */}
        <button
          type="button"
          onClick={() => logout()}
          className="flex w-full items-center gap-2 px-4 py-1.5 text-[11px] text-white/30 hover:text-white/55 transition-colors font-mono"
        >
          <span>↪</span>
          <span>Log out</span>
        </button>
      </div>

    </aside>
  )
}
