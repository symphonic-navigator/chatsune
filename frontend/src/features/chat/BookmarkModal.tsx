import { useEffect, useId, useRef, useState } from 'react'
import { useFocusTrap } from '../../app/hooks/useFocusTrap'
import { useUnsavedChangesGuard } from '../../app/hooks/useUnsavedChangesGuard'

interface BookmarkModalProps {
  isOpen: boolean
  onClose: () => void
  onSave: (title: string, scope: 'global' | 'local') => void | Promise<void>
  accentColour: string
}

export function BookmarkModal({ isOpen, onClose, onSave, accentColour }: BookmarkModalProps) {
  const [title, setTitle] = useState('')
  const [scope, setScope] = useState<'global' | 'local'>('global')
  const [saving, setSaving] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  const titleId = useId()
  const titleInputId = useId()

  const isDirty = title.trim().length > 0
  const { confirmingClose, attemptClose, confirmDiscard, cancelDiscard } =
    useUnsavedChangesGuard(isDirty, onClose)

  useFocusTrap(dialogRef, isOpen)

  // Escape key closes modal (focus restoration handled by useFocusTrap)
  useEffect(() => {
    if (!isOpen) return
    function onKey(e: KeyboardEvent) { if (e.key === 'Escape') attemptClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [isOpen, attemptClose])

  // Auto-focus title input when modal opens
  useEffect(() => {
    if (isOpen) {
      setTitle('')
      setScope('global')
      setSaving(false)
      // Defer focus to next frame so the element is mounted
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }, [isOpen])

  if (!isOpen) return null

  async function handleSave() {
    if (!title.trim() || saving) return
    setSaving(true)
    try {
      await onSave(title.trim(), scope)
      setTitle('')
      setScope('global')
    } finally {
      setSaving(false)
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSave()
    }
  }

  const borderColour = accentColour + '26'

  return (
    <>
      <div className="fixed inset-0 bg-black/60 z-30" onClick={attemptClose} aria-hidden />

      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="fixed z-40 top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 flex flex-col rounded-xl shadow-2xl overflow-hidden w-[calc(100vw-2rem)] sm:w-[360px]"
        style={{ backgroundColor: '#13101e', border: `1px solid ${borderColour}` }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-white/6">
          <span id={titleId} className="font-mono text-[13px] font-semibold text-white/80">Bookmark</span>
          <button
            type="button"
            onClick={attemptClose}
            aria-label="Close bookmark dialog"
            className="flex h-6 w-6 items-center justify-center rounded text-[12px] text-white/40 hover:bg-white/8 hover:text-white/70 transition-colors cursor-pointer"
          >
            ✕
          </button>
        </div>

        {confirmingClose && (
          <div className="border-b border-amber-400/30 bg-amber-400/10 px-5 py-3">
            <p className="text-[11px] text-amber-200 font-mono mb-2">
              Discard unsaved bookmark?
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
          {/* Title input */}
          <div className="flex flex-col gap-1.5">
            <label htmlFor={titleInputId} className="font-mono text-[11px] text-white/60 uppercase tracking-wider">
              Title
            </label>
            <input
              ref={inputRef}
              id={titleInputId}
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Enter bookmark title..."
              className="w-full bg-white/[0.04] border border-white/10 rounded-lg px-3 py-2 text-[13px] font-mono text-white/90 placeholder:text-white/25 outline-none focus:border-white/20 transition-colors"
            />
          </div>

          {/* Scope toggle */}
          <div className="flex flex-col gap-1.5">
            <span className="font-mono text-[11px] text-white/60 uppercase tracking-wider">
              Scope
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setScope('local')}
                className="flex-1 rounded-lg px-3 py-2 text-[12px] font-mono font-semibold transition-colors cursor-pointer border"
                style={scope === 'local'
                  ? { backgroundColor: accentColour + '1a', borderColor: accentColour + '40', color: accentColour }
                  : { backgroundColor: 'rgba(255,255,255,0.04)', borderColor: 'rgba(255,255,255,0.08)', color: 'rgba(255,255,255,0.5)' }
                }
              >
                Local
              </button>
              <button
                type="button"
                onClick={() => setScope('global')}
                className="flex-1 rounded-lg px-3 py-2 text-[12px] font-mono font-semibold transition-colors cursor-pointer border"
                style={scope === 'global'
                  ? { backgroundColor: accentColour + '1a', borderColor: accentColour + '40', color: accentColour }
                  : { backgroundColor: 'rgba(255,255,255,0.04)', borderColor: 'rgba(255,255,255,0.08)', color: 'rgba(255,255,255,0.5)' }
                }
              >
                Global
              </button>
            </div>
            <p className="font-mono text-[11px] text-white/60 leading-relaxed mt-0.5">
              {scope === 'local'
                ? 'Only visible in this chat session. Will not appear in your Bookmarks sidebar or other chats.'
                : 'Saved to your bookmarks — accessible from any chat and the Bookmarks sidebar.'}
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center gap-2 px-5 py-3 border-t border-white/6">
          <div className="flex-1" />
          <button
            type="button"
            onClick={attemptClose}
            className="px-3 py-1.5 rounded text-[12px] font-mono text-white/60 bg-white/6 hover:bg-white/10 hover:text-white/80 transition-colors cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={!title.trim() || saving}
            className="px-4 py-1.5 rounded text-[12px] font-mono font-semibold transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
            style={{
              backgroundColor: title.trim() && !saving ? accentColour : undefined,
              color: title.trim() && !saving ? '#13101e' : undefined,
            }}
          >
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    </>
  )
}
