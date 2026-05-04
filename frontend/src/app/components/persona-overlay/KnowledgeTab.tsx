import { useEffect, useRef, useState } from 'react'
import type { ChakraPaletteEntry } from '../../../core/types/chakra'
import type { PersonaDto } from '../../../core/types/persona'
import { knowledgeApi } from '../../../core/api/knowledge'
import { useKnowledgeStore } from '../../../core/store/knowledgeStore'
import { useSanitisedMode } from '../../../core/store/sanitisedModeStore'
import { KissMarkIcon } from '../../../core/components/symbols'

interface KnowledgeTabProps {
  persona: PersonaDto
  chakra: ChakraPaletteEntry
}

export function KnowledgeTab({ persona, chakra }: KnowledgeTabProps) {
  const { libraries, fetchLibraries } = useKnowledgeStore()
  const { isSanitised } = useSanitisedMode()

  const [assignedIds, setAssignedIds] = useState<string[]>([])
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)

  // Fetch assigned library IDs and all libraries on mount
  useEffect(() => {
    void fetchLibraries()
    knowledgeApi.getPersonaKnowledge(persona.id).then((r) => {
      setAssignedIds(r.library_ids)
    }).catch(() => {/* ignore */})
  }, [persona.id, fetchLibraries])

  // Close dropdown on outside click
  useEffect(() => {
    if (!dropdownOpen) return
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [dropdownOpen])

  const assignedLibraries = libraries.filter((l) => assignedIds.includes(l.id))
  const unassignedLibraries = libraries.filter((l) => !assignedIds.includes(l.id))

  const visibleAssigned = isSanitised
    ? assignedLibraries.filter((l) => !l.nsfw)
    : assignedLibraries

  const visibleUnassigned = isSanitised
    ? unassignedLibraries.filter((l) => !l.nsfw)
    : unassignedLibraries

  const hasNsfwLibraries = libraries.some((l) => l.nsfw)

  const handleAssign = async (libraryId: string) => {
    const updated = [...assignedIds, libraryId]
    setAssignedIds(updated)
    setDropdownOpen(false)
    await knowledgeApi.setPersonaKnowledge(persona.id, updated)
  }

  const handleRemove = async (libraryId: string) => {
    const updated = assignedIds.filter((id) => id !== libraryId)
    setAssignedIds(updated)
    await knowledgeApi.setPersonaKnowledge(persona.id, updated)
  }

  return (
    <div className="flex flex-col gap-4 p-1">
      <p className="font-mono text-[12px] text-white/40">
        Assigned libraries are available in every chat with this persona.
      </p>

      {/* Assigned libraries */}
      {visibleAssigned.length > 0 && (
        <div className="flex flex-col gap-2">
          {visibleAssigned.map((lib) => (
            <div
              key={lib.id}
              className="flex items-center justify-between px-3 py-2 rounded text-[13px]"
              style={{
                background: `${chakra.hex}0D`,
                border: `1px solid ${chakra.hex}33`,
              }}
            >
              <div className="flex items-center gap-2 min-w-0">
                <span className="font-medium text-white/90 truncate">{lib.name}</span>
                <span className="text-white/40 text-[11px] shrink-0">
                  {lib.document_count} doc{lib.document_count !== 1 ? 's' : ''}
                </span>
                {lib.nsfw && <span className="shrink-0"><KissMarkIcon /></span>}
              </div>
              <button
                onClick={() => handleRemove(lib.id)}
                className="ml-3 text-white/60 hover:text-white/90 transition-colors shrink-0 font-mono text-[14px] leading-none"
                aria-label={`Remove ${lib.name}`}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Assign button with dropdown */}
      <div className="relative" ref={dropdownRef}>
        <button
          onClick={() => setDropdownOpen((v) => !v)}
          className="font-mono text-[12px] px-3 py-2 rounded transition-colors w-full text-left"
          style={{
            border: `1px dashed ${chakra.hex}66`,
            color: chakra.hex,
          }}
        >
          + Assign Library
        </button>

        {dropdownOpen && (
          <div
            className="absolute left-0 right-0 mt-1 rounded overflow-hidden z-10"
            style={{
              background: '#1a1a2e',
              border: `1px solid ${chakra.hex}33`,
            }}
          >
            {visibleUnassigned.length === 0 ? (
              <div className="px-3 py-2 text-[12px] text-white/60 font-mono">
                No libraries available
              </div>
            ) : (
              visibleUnassigned.map((lib) => (
                <button
                  key={lib.id}
                  onClick={() => handleAssign(lib.id)}
                  className="flex items-center gap-2 w-full px-3 py-2 text-[13px] text-white/80 hover:text-white text-left transition-colors"
                  style={{ background: 'transparent' }}
                  onMouseEnter={(e) => {
                    ;(e.currentTarget as HTMLButtonElement).style.background = `${chakra.hex}1A`
                  }}
                  onMouseLeave={(e) => {
                    ;(e.currentTarget as HTMLButtonElement).style.background = 'transparent'
                  }}
                >
                  <span className="truncate">{lib.name}</span>
                  <span className="text-white/60 text-[11px] shrink-0 ml-auto">
                    {lib.document_count} doc{lib.document_count !== 1 ? 's' : ''}
                  </span>
                  {lib.nsfw && <span className="shrink-0"><KissMarkIcon /></span>}
                </button>
              ))
            )}
          </div>
        )}
      </div>

      {/* Sanitised mode note */}
      {hasNsfwLibraries && !isSanitised && (
        <p className="font-mono text-[11px] text-white/60 inline-flex items-center gap-1">
          <KissMarkIcon /> libraries are hidden when sanitised mode is active
        </p>
      )}
    </div>
  )
}
