import { useEffect, useState } from 'react'
import { knowledgeApi } from '../../core/api/knowledge'
import type { KnowledgeLibraryDto } from '../../core/types/knowledge'

interface KnowledgeDropdownProps {
  personaId: string
  personaName: string
  sessionId: string
  isOpen: boolean
  onClose: () => void
  /** When true, render a read-only list — no checkbox, no toggling. Used by
   *  hover-driven previews where deselection is not allowed. */
  readonly?: boolean
}

export function KnowledgeDropdown({
  personaId,
  personaName,
  sessionId,
  isOpen,
  onClose,
  readonly = false,
}: KnowledgeDropdownProps) {
  const [libraries, setLibraries] = useState<KnowledgeLibraryDto[]>([])
  const [personaLibraryIds, setPersonaLibraryIds] = useState<Set<string>>(new Set())
  const [sessionLibraryIds, setSessionLibraryIds] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!isOpen) return

    setLoading(true)

    Promise.all([
      knowledgeApi.listLibraries(),
      knowledgeApi.getPersonaKnowledge(personaId),
      knowledgeApi.getSessionKnowledge(sessionId),
    ])
      .then(([libs, personaKnowledge, sessionKnowledge]) => {
        setLibraries(libs)
        setPersonaLibraryIds(new Set(personaKnowledge.library_ids))
        setSessionLibraryIds(new Set(sessionKnowledge.library_ids))
      })
      .finally(() => setLoading(false))
  }, [isOpen, personaId, sessionId])

  // Editable mode: list libraries the user could still add to this session
  // (those not already assigned at persona level). Read-only mode: list the
  // libraries actually connected to this chat — persona-level plus session
  // additions — so the hover preview shows what the model has access to.
  const visibleLibraries = readonly
    ? libraries.filter(
        (lib) => personaLibraryIds.has(lib.id) || sessionLibraryIds.has(lib.id),
      )
    : libraries.filter(
        (lib) => !lib.nsfw && !personaLibraryIds.has(lib.id),
      )

  async function handleToggle(libraryId: string) {
    const updated = new Set(sessionLibraryIds)
    if (updated.has(libraryId)) {
      updated.delete(libraryId)
    } else {
      updated.add(libraryId)
    }
    setSessionLibraryIds(updated)
    await knowledgeApi.setSessionKnowledge(sessionId, Array.from(updated))
  }

  if (!isOpen) return null

  return (
    <>
      {/* Backdrop — skipped in read-only mode (hover-driven, no click-out needed) */}
      {!readonly && <div className="fixed inset-0 z-10" onClick={onClose} />}

      {/* Dropdown panel */}
      <div
        className="absolute left-0 top-full z-20 mt-1.5 w-72 rounded-lg shadow-xl overflow-hidden"
        style={{
          background: 'rgba(26, 21, 40, 0.98)',
          border: '1px solid rgba(140,118,215,0.2)',
        }}
      >
        <div className="px-3.5 pt-3 pb-2">
          <p className="text-[11px] leading-snug" style={{ color: 'rgba(140,118,215,0.6)' }}>
            {readonly ? (
              <>Knowledge libraries connected to this chat.</>
            ) : (
              <>Libraries already assigned to <span className="font-medium" style={{ color: 'rgba(140,118,215,0.85)' }}>{personaName}</span> are not shown here.</>
            )}
          </p>
        </div>

        <div className="max-h-64 overflow-y-auto">
          {loading && (
            <div className="px-3.5 py-3 text-[12px] text-white/30">Loading…</div>
          )}

          {!loading && visibleLibraries.length === 0 && (
            <div className="px-3.5 py-3 text-[12px] text-white/30">
              {readonly ? 'No libraries connected.' : 'No libraries available.'}
            </div>
          )}

          {!loading && readonly &&
            visibleLibraries.map((lib) => (
              <div
                key={lib.id}
                className="flex w-full items-center gap-2.5 px-3.5 py-2"
              >
                <span className="flex-1 min-w-0">
                  <span className="block truncate text-[12px] font-medium text-white/80">
                    {lib.name}
                  </span>
                  {lib.description && (
                    <span className="block truncate text-[11px] text-white/35">
                      {lib.description}
                    </span>
                  )}
                </span>
                <span className="flex-shrink-0 text-[10px] text-white/25">
                  {lib.document_count} doc{lib.document_count !== 1 ? 's' : ''}
                </span>
              </div>
            ))}

          {!loading && !readonly &&
            visibleLibraries.map((lib) => {
              const checked = sessionLibraryIds.has(lib.id)
              return (
                <button
                  key={lib.id}
                  type="button"
                  onClick={() => handleToggle(lib.id)}
                  className="flex w-full items-center gap-2.5 px-3.5 py-2 text-left transition-colors hover:bg-white/5"
                >
                  {/* Checkbox */}
                  <span
                    className="flex h-4 w-4 flex-shrink-0 items-center justify-center rounded"
                    style={
                      checked
                        ? { background: '#8C76D7' }
                        : { border: '1.5px solid rgba(140,118,215,0.4)' }
                    }
                  >
                    {checked && (
                      <svg width="9" height="7" viewBox="0 0 9 7" fill="none">
                        <path
                          d="M1 3.5L3.5 6L8 1"
                          stroke="white"
                          strokeWidth="1.5"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    )}
                  </span>

                  <span className="flex-1 min-w-0">
                    <span className="block truncate text-[12px] font-medium text-white/80">
                      {lib.name}
                    </span>
                    {lib.description && (
                      <span className="block truncate text-[11px] text-white/35">
                        {lib.description}
                      </span>
                    )}
                  </span>

                  <span className="flex-shrink-0 text-[10px] text-white/25">
                    {lib.document_count} doc{lib.document_count !== 1 ? 's' : ''}
                  </span>
                </button>
              )
            })}
        </div>
      </div>
    </>
  )
}
