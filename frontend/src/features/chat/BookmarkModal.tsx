import { useEffect, useRef, useState } from 'react'

interface BookmarkModalProps {
  isOpen: boolean
  onClose: () => void
  onSave: (title: string, scope: 'global' | 'local') => void | Promise<void>
  accentColour: string
}

export function BookmarkModal({ isOpen, onClose, onSave, accentColour }: BookmarkModalProps) {
  const [title, setTitle] = useState('')
  const [scope, setScope] = useState<'global' | 'local'>('local')
  const [saving, setSaving] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  // Escape key closes modal; save/restore focus
  const previousFocusRef = useRef<Element | null>(null)
  useEffect(() => {
    if (!isOpen) return
    previousFocusRef.current = document.activeElement
    function onKey(e: KeyboardEvent) { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      if (previousFocusRef.current instanceof HTMLElement) {
        previousFocusRef.current.focus()
      }
    }
  }, [isOpen, onClose])

  // Auto-focus title input when modal opens
  useEffect(() => {
    if (isOpen) {
      setTitle('')
      setScope('local')
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
      setScope('local')
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
      <div className="fixed inset-0 bg-black/60 z-30" onClick={onClose} aria-hidden />

      <div
        role="dialog"
        aria-modal="true"
        aria-label="Bookmark"
        className="fixed z-40 top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 flex flex-col rounded-xl shadow-2xl overflow-hidden"
        style={{ backgroundColor: '#13101e', border: `1px solid ${borderColour}`, width: 360 }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-white/6">
          <span className="font-mono text-[13px] font-semibold text-white/80">Bookmark</span>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex h-6 w-6 items-center justify-center rounded text-[12px] text-white/40 hover:bg-white/8 hover:text-white/70 transition-colors cursor-pointer"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="flex flex-col gap-4 px-5 py-4">
          {/* Title input */}
          <div className="flex flex-col gap-1.5">
            <label htmlFor="bookmark-title" className="font-mono text-[11px] text-white/40 uppercase tracking-wider">
              Title
            </label>
            <input
              ref={inputRef}
              id="bookmark-title"
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
            <span className="font-mono text-[11px] text-white/40 uppercase tracking-wider">
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
            <p className="font-mono text-[11px] text-white/30 leading-relaxed mt-0.5">
              {scope === 'local'
                ? 'Only visible within this chat session.'
                : 'Visible in your bookmarks list across all sessions.'}
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center gap-2 px-5 py-3 border-t border-white/6">
          <div className="flex-1" />
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 rounded text-[12px] font-mono text-white/50 bg-white/6 hover:bg-white/10 hover:text-white/70 transition-colors cursor-pointer"
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
