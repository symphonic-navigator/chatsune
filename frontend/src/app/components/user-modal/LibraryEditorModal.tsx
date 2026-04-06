import { useEffect, useRef, useState } from 'react'

interface LibraryEditorModalProps {
  initial?: { name: string; description: string; nsfw: boolean }
  onSave: (data: { name: string; description: string; nsfw: boolean }) => Promise<void>
  onDelete?: () => Promise<void>
  onClose: () => void
}

export function LibraryEditorModal({ initial, onSave, onDelete, onClose }: LibraryEditorModalProps) {
  const [name, setName] = useState(initial?.name ?? '')
  const [description, setDescription] = useState(initial?.description ?? '')
  const [nsfw, setNsfw] = useState(initial?.nsfw ?? false)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const nameRef = useRef<HTMLInputElement>(null)
  const deleteTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const isEdit = initial !== undefined

  useEffect(() => {
    nameRef.current?.focus()
    return () => {
      if (deleteTimerRef.current) clearTimeout(deleteTimerRef.current)
    }
  }, [])

  async function handleSave() {
    if (!name.trim()) return
    setSaving(true)
    setError(null)
    try {
      await onSave({ name: name.trim(), description: description.trim(), nsfw })
      onClose()
    } catch {
      setError('Failed to save library')
      setSaving(false)
    }
  }

  function handleDeleteClick() {
    if (!onDelete) return
    if (confirmDelete) {
      setDeleting(true)
      onDelete()
        .then(() => onClose())
        .catch(() => {
          setError('Failed to delete library')
          setDeleting(false)
          setConfirmDelete(false)
        })
    } else {
      setConfirmDelete(true)
      deleteTimerRef.current = setTimeout(() => setConfirmDelete(false), 3000)
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Escape') onClose()
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
      onKeyDown={handleKeyDown}
    >
      <div className="w-full max-w-md rounded-xl border border-white/8 bg-elevated shadow-2xl">
        {/* Header */}
        <div className="border-b border-white/6 px-5 py-4">
          <h2 className="text-[13px] font-mono uppercase tracking-wider text-white/60">
            {isEdit ? 'Edit Library' : 'New Library'}
          </h2>
        </div>

        {/* Body */}
        <div className="flex flex-col gap-4 px-5 py-4">
          {error && (
            <p className="rounded-lg border border-red-400/20 bg-red-400/5 px-3 py-2 text-[11px] text-red-400 font-mono">
              {error}
            </p>
          )}

          <div className="flex flex-col gap-1.5">
            <label className="text-[11px] font-mono uppercase tracking-wider text-white/40">
              Name
            </label>
            <input
              ref={nameRef}
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value.slice(0, 200))}
              maxLength={200}
              placeholder="Library name..."
              className="rounded-lg border border-white/8 bg-surface px-3 py-2 text-[13px] text-white/80 placeholder-white/20 outline-none transition-colors focus:border-gold/30"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-[11px] font-mono uppercase tracking-wider text-white/40">
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value.slice(0, 1000))}
              maxLength={1000}
              rows={3}
              placeholder="Optional description..."
              className="resize-none rounded-lg border border-white/8 bg-surface px-3 py-2 text-[13px] text-white/80 placeholder-white/20 outline-none transition-colors focus:border-gold/30"
            />
          </div>

          <label className="flex cursor-pointer items-center gap-3">
            <input
              type="checkbox"
              checked={nsfw}
              onChange={(e) => setNsfw(e.target.checked)}
              className="h-3.5 w-3.5 cursor-pointer accent-gold"
            />
            <span className="text-[12px] text-white/60">
              💋 NSFW content
            </span>
          </label>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-white/6 px-5 py-3">
          <div>
            {isEdit && onDelete && (
              <button
                type="button"
                onClick={handleDeleteClick}
                disabled={deleting}
                className={[
                  'rounded px-2.5 py-1 text-[10px] font-mono uppercase tracking-wider border transition-colors',
                  confirmDelete
                    ? 'border-red-400/40 bg-red-400/10 text-red-400 hover:bg-red-400/15'
                    : 'border-white/8 text-white/30 hover:border-red-400/30 hover:text-red-400',
                  deleting ? 'cursor-not-allowed opacity-30' : 'cursor-pointer',
                ].join(' ')}
              >
                {deleting ? 'Deleting...' : confirmDelete ? 'Sure?' : 'Delete'}
              </button>
            )}
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={saving || deleting}
              className="rounded border border-white/8 px-2.5 py-1 text-[10px] font-mono uppercase tracking-wider text-white/40 transition-colors hover:border-white/15 hover:text-white/60 cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={!name.trim() || saving || deleting}
              className={[
                'rounded border border-gold/30 px-2.5 py-1 text-[10px] font-mono uppercase tracking-wider text-gold transition-colors',
                !name.trim() || saving || deleting
                  ? 'cursor-not-allowed opacity-30'
                  : 'cursor-pointer hover:bg-gold/10 hover:border-gold/40',
              ].join(' ')}
            >
              {saving ? 'Saving...' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
