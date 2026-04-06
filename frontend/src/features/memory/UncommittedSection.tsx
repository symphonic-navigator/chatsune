import { useState } from 'react'
import type { JournalEntryDto } from '../../core/api/memory'
import { memoryApi } from '../../core/api/memory'

interface Props {
  personaId: string
  entries: JournalEntryDto[]
}

export default function UncommittedSection({ personaId, entries }: Props) {
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [busy, setBusy] = useState(false)

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleAll = () => {
    if (selected.size === entries.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(entries.map((e) => e.id)))
    }
  }

  const handleCommit = async (ids: string[]) => {
    if (busy || ids.length === 0) return
    setBusy(true)
    try {
      await memoryApi.commitEntries(personaId, ids)
      setSelected(new Set())
    } finally {
      setBusy(false)
    }
  }

  const handleDelete = async (ids: string[]) => {
    if (busy || ids.length === 0) return
    setBusy(true)
    try {
      await memoryApi.deleteEntries(personaId, ids)
      setSelected((prev) => {
        const next = new Set(prev)
        ids.forEach((id) => next.delete(id))
        return next
      })
    } finally {
      setBusy(false)
    }
  }

  const startEdit = (entry: JournalEntryDto) => {
    setEditingId(entry.id)
    setEditValue(entry.content)
  }

  const cancelEdit = () => {
    setEditingId(null)
    setEditValue('')
  }

  const saveEdit = async (entryId: string) => {
    if (busy) return
    setBusy(true)
    try {
      await memoryApi.updateEntry(personaId, entryId, editValue)
      setEditingId(null)
      setEditValue('')
    } finally {
      setBusy(false)
    }
  }

  const selectionActive = selected.size > 0

  return (
    <div className="rounded-lg border border-white/5 bg-surface overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/5">
        <span className="text-xs text-white/60 font-medium">
          Uncommitted — {entries.length} {entries.length === 1 ? 'entry' : 'entries'}
        </span>
        <div className="flex items-center gap-2">
          {selectionActive && (
            <>
              <button
                onClick={() => handleCommit(Array.from(selected))}
                disabled={busy}
                className="px-2.5 py-1 rounded text-[11px] bg-green-500/10 text-green-400 hover:bg-green-500/20 disabled:opacity-40 transition-colors"
              >
                Commit {selected.size}
              </button>
              <button
                onClick={() => handleDelete(Array.from(selected))}
                disabled={busy}
                className="px-2.5 py-1 rounded text-[11px] bg-red-500/10 text-red-400 hover:bg-red-500/20 disabled:opacity-40 transition-colors"
              >
                Delete {selected.size}
              </button>
            </>
          )}
          {entries.length > 0 && (
            <button
              onClick={() => handleCommit(entries.map((e) => e.id))}
              disabled={busy}
              className="px-2.5 py-1 rounded text-[11px] bg-green-500/10 text-green-400 hover:bg-green-500/20 disabled:opacity-40 transition-colors"
            >
              Commit All
            </button>
          )}
        </div>
      </div>

      {entries.length === 0 ? (
        <div className="px-4 py-8 text-center text-[13px] text-white/20">
          No uncommitted entries
        </div>
      ) : (
        <div>
          <div className="flex items-center gap-3 px-4 py-2 border-b border-white/5">
            <input
              type="checkbox"
              checked={selected.size === entries.length && entries.length > 0}
              onChange={toggleAll}
              className="accent-blue-400"
            />
            <span className="text-[11px] text-white/30">Select all</span>
          </div>

          <ul className="divide-y divide-white/5">
            {entries.map((entry) => (
              <li key={entry.id} className="flex gap-3 px-4 py-3">
                <div className="pt-0.5">
                  <input
                    type="checkbox"
                    checked={selected.has(entry.id)}
                    onChange={() => toggleSelect(entry.id)}
                    className="accent-blue-400"
                  />
                </div>
                <div className="flex-1 min-w-0">
                  {editingId === entry.id ? (
                    <div className="space-y-2">
                      <textarea
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        rows={3}
                        className="w-full rounded bg-base border border-white/10 px-2 py-1.5 text-sm text-white/80 resize-none focus:outline-none focus:border-white/20"
                      />
                      <div className="flex gap-2">
                        <button
                          onClick={() => saveEdit(entry.id)}
                          disabled={busy}
                          className="px-2.5 py-1 rounded text-[11px] bg-green-500/10 text-green-400 hover:bg-green-500/20 disabled:opacity-40 transition-colors"
                        >
                          Save
                        </button>
                        <button
                          onClick={cancelEdit}
                          className="px-2.5 py-1 rounded text-[11px] text-white/40 hover:text-white/60 transition-colors"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <p className="text-sm text-white/80 leading-relaxed">{entry.content}</p>
                      <div className="flex flex-wrap items-center gap-2 mt-1.5">
                        <span className="text-[11px] text-white/30">
                          {new Date(entry.created_at).toLocaleString()}
                        </span>
                        <span className="text-[11px] text-white/20">
                          {(() => {
                            const hoursRemaining = 48 - (Date.now() - new Date(entry.created_at).getTime()) / 3_600_000
                            if (hoursRemaining <= 0) return 'Auto-commit soon'
                            return `Auto-commit in ${Math.ceil(hoursRemaining)}h`
                          })()}
                        </span>
                        {entry.category && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] bg-white/5 text-white/40">
                            {entry.category}
                          </span>
                        )}
                        {entry.is_correction && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] bg-amber-500/10 text-amber-400">
                            correction
                          </span>
                        )}
                      </div>
                    </>
                  )}
                </div>
                {editingId !== entry.id && (
                  <div className="flex flex-col gap-1 shrink-0">
                    <button
                      onClick={() => handleCommit([entry.id])}
                      disabled={busy}
                      className="px-2 py-0.5 rounded text-[11px] bg-green-500/10 text-green-400 hover:bg-green-500/20 disabled:opacity-40 transition-colors"
                    >
                      Commit
                    </button>
                    <button
                      onClick={() => startEdit(entry)}
                      disabled={busy}
                      className="px-2 py-0.5 rounded text-[11px] text-white/40 hover:text-white/60 transition-colors"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => handleDelete([entry.id])}
                      disabled={busy}
                      className="px-2 py-0.5 rounded text-[11px] bg-red-500/10 text-red-400 hover:bg-red-500/20 disabled:opacity-40 transition-colors"
                    >
                      Delete
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
