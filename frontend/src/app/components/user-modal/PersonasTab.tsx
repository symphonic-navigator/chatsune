import { useEffect, useMemo } from 'react'
import {
  DndContext,
  closestCenter,
  type DragEndEvent,
  type DraggableAttributes,
  type DraggableSyntheticListeners,
} from '@dnd-kit/core'
import { SortableContext, verticalListSortingStrategy, useSortable, arrayMove } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { zoomModifiers } from '../../../core/utils/dndZoomModifier'
import { usePersonas } from '../../../core/hooks/usePersonas'
import { useDndSensors } from '../../../core/hooks/useDndSensors'
import { useSanitisedMode } from '../../../core/store/sanitisedModeStore'
import { CHAKRA_PALETTE } from '../../../core/types/chakra'
import { CroppedAvatar } from '../avatar-crop/CroppedAvatar'
import type { PersonaDto } from '../../../core/types/persona'
import { sortPersonas } from '../sidebar/personaSort'

interface PersonasTabProps {
  onOpenPersonaOverlay: (personaId: string) => void
}

export function PersonasTab({ onOpenPersonaOverlay }: PersonasTabProps) {
  const { personas, update, reorder } = usePersonas()
  const isSanitised = useSanitisedMode((s) => s.isSanitised)
  const dndSensors = useDndSensors()

  const visible = useMemo(() => {
    const filtered = isSanitised ? personas.filter((p) => !p.nsfw) : personas
    return sortPersonas(filtered)
  }, [personas, isSanitised])

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id) return
    const oldIndex = visible.findIndex((p) => p.id === active.id)
    const newIndex = visible.findIndex((p) => p.id === over.id)
    if (oldIndex === -1 || newIndex === -1) return
    const reordered = arrayMove(visible, oldIndex, newIndex)
    reorder(reordered.map((p) => p.id))
  }

  // Test seam — exposes the same handler the DndContext uses, so unit tests
  // can drive reorder logic without simulating jsdom pointer events.
  useEffect(() => {
    if (typeof window === 'undefined') return
    ;(window as any).__personasTabTestHelper = {
      simulateReorder: (activeId: string, overId: string) => {
        handleDragEnd({ active: { id: activeId }, over: { id: overId } } as unknown as DragEndEvent)
      },
    }
    return () => {
      delete (window as any).__personasTabTestHelper
    }
  })

  return (
    <div className="flex flex-col gap-2 p-4">
      <DndContext sensors={dndSensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd} modifiers={zoomModifiers}>
        <SortableContext items={visible.map((p) => p.id)} strategy={verticalListSortingStrategy}>
          {visible.map((persona) => (
            <SortablePersonaRow
              key={persona.id}
              persona={persona}
              onOpen={() => onOpenPersonaOverlay(persona.id)}
              onTogglePin={() => update(persona.id, { pinned: !persona.pinned })}
            />
          ))}
        </SortableContext>
      </DndContext>
    </div>
  )
}

interface PersonaRowProps {
  persona: PersonaDto
  onOpen: () => void
  onTogglePin: () => void
  dragAttributes?: DraggableAttributes
  dragListeners?: DraggableSyntheticListeners
}

function SortablePersonaRow(props: PersonaRowProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: props.persona.id,
  })
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  }
  return (
    <div ref={setNodeRef} style={style}>
      <PersonaRow {...props} dragAttributes={attributes} dragListeners={listeners} />
    </div>
  )
}

function PersonaRow({ persona, onOpen, onTogglePin, dragAttributes, dragListeners }: PersonaRowProps) {
  const chakra = CHAKRA_PALETTE[persona.colour_scheme]
  const modelLabel = persona.model_unique_id.split(':').slice(1).join(':')

  return (
    <div
      data-testid="persona-row"
      data-persona-id={persona.id}
      className="relative flex items-center gap-3 rounded-lg px-3 py-2 transition-colors hover:bg-white/5"
      style={{ border: `1px solid ${chakra.hex}22` }}
    >
      <span
        data-testid="persona-drag-handle"
        className="cursor-grab select-none text-white/30"
        aria-hidden
        {...(dragAttributes ?? {})}
        {...(dragListeners ?? {})}
      >
        ≡
      </span>

      <div
        className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full"
        style={{ background: `${chakra.hex}22`, border: `1px solid ${chakra.hex}55` }}
      >
        {persona.profile_image ? (
          <CroppedAvatar
            personaId={persona.id}
            updatedAt={persona.updated_at}
            crop={persona.profile_crop}
            size={28}
            alt={persona.name}
          />
        ) : (
          <span className="text-[11px] font-semibold" style={{ color: chakra.hex }}>
            {persona.monogram}
          </span>
        )}
      </div>

      <button
        type="button"
        data-testid="persona-row-body"
        onClick={onOpen}
        className="flex min-w-0 flex-1 flex-col items-start bg-transparent border-none p-0 text-left cursor-pointer"
      >
        <span className="truncate text-[13px] font-medium text-white/90">{persona.name}</span>
        {persona.tagline && (
          <span className="truncate text-[11px] text-white/45">{persona.tagline}</span>
        )}
        <span
          className="truncate font-mono text-[10px]"
          style={{ color: chakra.hex + '4d', letterSpacing: '0.5px' }}
        >
          {modelLabel}
        </span>
      </button>

      {persona.nsfw && (
        <span
          data-testid="persona-nsfw-indicator"
          className="absolute top-1 right-1 text-[10px] leading-none"
          aria-label="NSFW"
          title="NSFW"
        >
          💋
        </span>
      )}

      <button
        type="button"
        data-testid="persona-pin-toggle"
        onClick={(e) => {
          e.stopPropagation()
          onTogglePin()
        }}
        className="rounded p-1 transition-colors"
        style={{
          color: persona.pinned ? chakra.hex : 'rgba(255,255,255,0.2)',
          background: persona.pinned ? chakra.hex + '1a' : 'transparent',
        }}
        aria-label={persona.pinned ? 'Unpin' : 'Pin'}
        title={persona.pinned ? 'Unpin' : 'Pin'}
      >
        📌
      </button>
    </div>
  )
}
