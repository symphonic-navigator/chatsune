import { useNavigate } from 'react-router-dom'
import { memoryApi, type JournalEntryDto } from '../../core/api/memory'
import { useMemoryStore } from '../../core/store/memoryStore'

interface JournalDropdownProps {
  personaId: string
  entries: JournalEntryDto[]
  canTriggerExtraction: boolean
  onClose: () => void
}

function relativeTime(isoString: string): string {
  const diffMs = Date.now() - new Date(isoString).getTime()
  const diffSec = Math.floor(diffMs / 1000)
  if (diffSec < 60) return `${diffSec}s ago`
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  return `${Math.floor(diffHr / 24)}d ago`
}

export function JournalDropdown({ personaId, entries, canTriggerExtraction, onClose }: JournalDropdownProps) {
  const navigate = useNavigate()
  const store = useMemoryStore.getState

  const visibleEntries = entries.slice(0, 10)

  const handleCommit = async (entry: JournalEntryDto) => {
    try {
      await memoryApi.commitEntries(personaId, [entry.id])
      store().commitEntry(personaId, entry)
    } catch {
      // silently fail — WS event will correct state
    }
  }

  const handleDelete = async (entry: JournalEntryDto) => {
    try {
      await memoryApi.deleteEntries(personaId, [entry.id])
      store().removeEntry(personaId, entry.id)
    } catch {
      // silently fail — WS event will correct state
    }
  }

  const handleExtract = async () => {
    try {
      await memoryApi.triggerExtraction(personaId)
    } catch {
      // silently fail — extraction started event will update state
    }
  }

  return (
    <>
      {/* Backdrop to close on outside click */}
      <div className="fixed inset-0 z-40" onClick={onClose} />

      <div className="absolute right-0 top-full z-50 mt-1 w-80 rounded-lg border border-white/10 bg-elevated shadow-xl">
        <div className="border-b border-white/8 px-3 py-2">
          <span className="text-[11px] font-medium uppercase tracking-wide text-white/40">
            Uncommitted Journal Entries
          </span>
        </div>

        {visibleEntries.length === 0 ? (
          <div className="px-3 py-4 text-center text-[12px] text-white/30">
            No uncommitted entries
          </div>
        ) : (
          <div className="max-h-72 overflow-y-auto">
            {visibleEntries.map((entry) => (
              <div key={entry.id} className="border-b border-white/5 px-3 py-2 last:border-0">
                <div className="mb-1 flex items-start justify-between gap-2">
                  <p className="flex-1 text-[12px] leading-relaxed text-white/70">{entry.content}</p>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-white/25">{relativeTime(entry.created_at)}</span>
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      onClick={() => handleCommit(entry)}
                      className="rounded px-1.5 py-0.5 text-[10px] text-green-400/70 hover:bg-green-500/10 hover:text-green-400 transition-colors"
                      title="Commit entry"
                    >
                      Commit
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDelete(entry)}
                      className="rounded px-1.5 py-0.5 text-[10px] text-white/30 hover:bg-red-500/10 hover:text-red-400/70 transition-colors"
                      title="Delete entry"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        <div className="border-t border-white/8 px-3 py-2 flex items-center justify-between gap-2">
          {canTriggerExtraction && (
            <button
              type="button"
              onClick={handleExtract}
              className="rounded-md border border-white/10 px-2 py-1 text-[11px] text-white/50 hover:bg-white/5 hover:text-white/70 transition-colors"
            >
              Extract Now
            </button>
          )}
          <button
            type="button"
            onClick={() => { navigate(`/memory/${personaId}`); onClose() }}
            className="ml-auto text-[11px] text-white/30 hover:text-white/50 transition-colors"
          >
            Open Memory Page →
          </button>
        </div>
      </div>
    </>
  )
}
