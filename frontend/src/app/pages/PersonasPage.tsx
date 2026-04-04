import {
  closestCenter,
  DndContext,
  DragOverlay,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core"
import { rectSortingStrategy, SortableContext } from "@dnd-kit/sortable"
import { useState } from "react"
import { useNavigate } from "react-router"
import PersonaCard from "../components/persona-card/PersonaCard"
import AddPersonaCard from "../components/persona-card/AddPersonaCard"
import { usePersonas } from "../../core/hooks/usePersonas"
import { useSanitisedModeStore } from "../../core/store/sanitisedModeStore"

export default function PersonasPage() {
  const { personas, reorder } = usePersonas()
  const isSanitised = useSanitisedModeStore((s) => s.isSanitised)
  const navigate = useNavigate()
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
    navigate(`/chat/${personaId}`)
  }

  const handleNewChat = (personaId: string) => {
    navigate(`/chat/${personaId}`)
  }

  const handleOpenOverlay = (_personaId: string) => {
    // Wired in Task 8
  }

  const handleAddPersona = () => {
    // Wired in Task 8
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
              />
            ))}
            <AddPersonaCard onClick={handleAddPersona} index={filtered.length} />
          </div>
        </SortableContext>
        <DragOverlay>
          {activePersona ? (
            <div style={{ transform: "scale(1.05)", opacity: 0.9 }}>
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
