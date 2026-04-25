import { useEffect, useId, useRef, useState } from 'react'
import { useFocusTrap } from '../../hooks/useFocusTrap'
import { useUnsavedChangesGuard } from '../../hooks/useUnsavedChangesGuard'
import { Sheet } from '../../../core/components/Sheet'
import { RefreshFrequencySelect, type RefreshFrequency } from '../../../features/knowledge/RefreshFrequencySelect'

interface LibraryEditorModalProps {
  initial?: { name: string; description: string; nsfw: boolean; default_refresh?: RefreshFrequency }
  onSave: (data: { name: string; description: string; nsfw: boolean; default_refresh: RefreshFrequency }) => Promise<void>
  onDelete?: () => Promise<void>
  onClose: () => void
}

export function LibraryEditorModal({ initial, onSave, onDelete, onClose }: LibraryEditorModalProps) {
  const [name, setName] = useState(initial?.name ?? '')
  const [description, setDescription] = useState(initial?.description ?? '')
  const [nsfw, setNsfw] = useState(initial?.nsfw ?? false)
  const [defaultRefresh, setDefaultRefresh] = useState<RefreshFrequency>(initial?.default_refresh ?? 'standard')
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const nameRef = useRef<HTMLInputElement>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  const deleteTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const nameId = useId()
  const descId = useId()
  const nsfwId = useId()
  const titleId = useId()

  const isEdit = initial !== undefined
  useFocusTrap(dialogRef, true)

  const isDirty =
    name !== (initial?.name ?? '') ||
    description !== (initial?.description ?? '') ||
    nsfw !== (initial?.nsfw ?? false) ||
    defaultRefresh !== (initial?.default_refresh ?? 'standard')
  const { confirmingClose, attemptClose, confirmDiscard, cancelDiscard } =
    useUnsavedChangesGuard(isDirty, onClose)

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
      await onSave({ name: name.trim(), description: description.trim(), nsfw, default_refresh: defaultRefresh })
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

  return (
    <Sheet isOpen={true} onClose={attemptClose} size="md" ariaLabel={isEdit ? 'Edit library' : 'New library'} className="border border-white/8 bg-elevated shadow-2xl">
      <div ref={dialogRef} aria-labelledby={titleId} className="flex flex-1 flex-col overflow-y-auto lg:flex-none lg:overflow-visible">
        {/* Header */}
        <div className="border-b border-white/6 px-5 py-4">
          <h2 id={titleId} className="text-[13px] font-mono uppercase tracking-wider text-white/60">
            {isEdit ? 'Edit Library' : 'New Library'}
          </h2>
        </div>

        {confirmingClose && (
          <div className="border-b border-amber-400/30 bg-amber-400/10 px-5 py-3">
            <p className="text-[11px] text-amber-200 font-mono mb-2">
              Discard unsaved changes?
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={cancelDiscard}
                className="rounded border border-white/15 px-2.5 py-1 text-[10px] font-mono uppercase tracking-wider text-white/60 hover:text-white/90 cursor-pointer"
              >
                Keep editing
              </button>
              <button
                type="button"
                onClick={confirmDiscard}
                className="rounded border border-amber-400/40 bg-amber-400/15 px-2.5 py-1 text-[10px] font-mono uppercase tracking-wider text-amber-200 hover:bg-amber-400/25 cursor-pointer"
              >
                Discard
              </button>
            </div>
          </div>
        )}

        {/* Body */}
        <div className="flex flex-col gap-4 px-5 py-4">
          {error && (
            <p className="rounded-lg border border-red-400/20 bg-red-400/5 px-3 py-2 text-[11px] text-red-400 font-mono">
              {error}
            </p>
          )}

          <div className="flex flex-col gap-1.5">
            <label htmlFor={nameId} className="text-[11px] font-mono uppercase tracking-wider text-white/60">
              Name
            </label>
            <input
              id={nameId}
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
            <label htmlFor={descId} className="text-[11px] font-mono uppercase tracking-wider text-white/60">
              Description
            </label>
            <textarea
              id={descId}
              value={description}
              onChange={(e) => setDescription(e.target.value.slice(0, 1000))}
              maxLength={1000}
              rows={3}
              placeholder="Optional description..."
              className="resize-none rounded-lg border border-white/8 bg-surface px-3 py-2 text-[13px] text-white/80 placeholder-white/20 outline-none transition-colors focus:border-gold/30"
            />
          </div>

          <label htmlFor={nsfwId} className="flex cursor-pointer items-center gap-3">
            <input
              id={nsfwId}
              type="checkbox"
              checked={nsfw}
              onChange={(e) => setNsfw(e.target.checked)}
              className="h-3.5 w-3.5 cursor-pointer accent-gold"
            />
            <span className="text-[12px] text-white/60">
              💋 NSFW content
            </span>
          </label>

          <div className="flex flex-col gap-1.5">
            <label className="text-[11px] font-mono uppercase tracking-wider text-white/60">
              Default refresh frequency for documents
            </label>
            <RefreshFrequencySelect
              value={defaultRefresh}
              onChange={(v) => v !== null && setDefaultRefresh(v)}
            />
          </div>
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
                    : 'border-white/8 text-white/60 hover:border-red-400/30 hover:text-red-400',
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
              onClick={attemptClose}
              disabled={saving || deleting}
              className="rounded border border-white/8 px-2.5 py-1 text-[10px] font-mono uppercase tracking-wider text-white/60 transition-colors hover:border-white/15 hover:text-white/80 cursor-pointer"
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
    </Sheet>
  )
}
