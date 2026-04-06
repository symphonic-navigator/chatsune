import {
  closestCenter,
  DndContext,
  DragOverlay,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core"
import { rectSortingStrategy, SortableContext } from "@dnd-kit/sortable"
import { useState } from "react"
import { useNavigate, useOutletContext } from "react-router-dom"
import PersonaCard from "../components/persona-card/PersonaCard"
import AddPersonaCard from "../components/persona-card/AddPersonaCard"
import { usePersonas } from "../../core/hooks/usePersonas"
import { useChatSessions } from "../../core/hooks/useChatSessions"
import { useSanitisedMode } from "../../core/store/sanitisedModeStore"
import type { PersonaOverlayTab } from "../components/persona-overlay/PersonaOverlay"

export default function PersonasPage() {
  const { personas, reorder, update } = usePersonas()
  const { sessions } = useChatSessions()
  const isSanitised = useSanitisedMode((s) => s.isSanitised)
  const navigate = useNavigate()
  const { openPersonaOverlay } = useOutletContext<{
    openPersonaOverlay: (personaId: string | null, tab?: PersonaOverlayTab) => void
  }>()
  const [activeId, setActiveId] = useState<string | null>(null)

  const filtered = isSanitised ? personas.filter((p) => !p.nsfw) : personas
  const activePersona = filtered.find((p) => p.id === activeId)

  const handleDragStart = (event: DragStartEvent) => {
    setActiveId(event.active.id as string)
  }

  const handleDragEnd = (event: DragEndEvent) => {
    setActiveId(null)
    const { active, over } = event
    if (!over || active.id === over.id) return
    const oldIndex = filtered.findIndex((p) => p.id === active.id)
    const newIndex = filtered.findIndex((p) => p.id === over.id)
    if (oldIndex === -1 || newIndex === -1) return
    const reordered = [...filtered]
    const [moved] = reordered.splice(oldIndex, 1)
    reordered.splice(newIndex, 0, moved)
    reorder(reordered.map((p) => p.id))
  }

  const handleContinue = (personaId: string) => {
    const lastSession = sessions.find((s) => s.persona_id === personaId)
    if (lastSession) {
      navigate(`/chat/${personaId}/${lastSession.id}`)
    } else {
      navigate(`/chat/${personaId}?new=1`)
    }
  }

  const handleNewChat = (personaId: string) => {
    navigate(`/chat/${personaId}?new=1`)
  }

  const handleOpenOverlay = (personaId: string, tab: PersonaOverlayTab) => {
    openPersonaOverlay(personaId, tab)
  }

  const handleTogglePin = (personaId: string, pinned: boolean) => {
    update(personaId, { pinned })
  }

  const handleAddPersona = () => {
    openPersonaOverlay(null, "edit")
  }

  return (
    <div className="h-full overflow-y-auto p-10">
      <DndContext
        collisionDetection={closestCenter}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
      >
        <SortableContext items={filtered.map((p) => p.id)} strategy={rectSortingStrategy}>
          <div
            className="flex flex-wrap justify-center gap-6"
            style={{ maxWidth: "1200px", margin: "0 auto" }}
          >
            {filtered.map((persona, index) => (
              <PersonaCard
                key={persona.id}
                persona={persona}
                index={index}
                onContinue={handleContinue}
                onNewChat={handleNewChat}
                onOpenOverlay={handleOpenOverlay}
                onTogglePin={handleTogglePin}
              />
            ))}
            <AddPersonaCard onClick={handleAddPersona} index={filtered.length} />
          </div>
        </SortableContext>
        <DragOverlay>
          {activePersona ? (
            <div style={{ transform: "scale(1.05)", opacity: 0.9, pointerEvents: "none" }}>
              <PersonaCard
                persona={activePersona}
                index={0}
                onContinue={() => {}}
                onNewChat={() => {}}
                onOpenOverlay={() => {}}
              />
            </div>
          ) : null}
        </DragOverlay>
      </DndContext>
    </div>
  )
}
