import { Suspense, lazy, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { useViewport } from '../../core/hooks/useViewport'
import { useRecentEmojisStore } from './recentEmojisStore'
import { LRUBar } from './LRUBar'

const Picker = lazy(() => import('@emoji-mart/react').then((m) => ({ default: m.default })))

async function loadEmojiData() {
  return (await import('@emoji-mart/data')).default
}

interface Props {
  onSelect: (emoji: string) => void
  onClose: () => void
  /**
   * Optional override for the LRU strip at the top of the picker.
   * Defaults to the message-emoji store. The project create / edit
   * modals use this to surface ``recent_project_emojis`` instead, so
   * the message and project pickers each maintain their own recency.
   */
  recentEmojis?: string[]
  /**
   * When true, render as a centred full-screen overlay portalled to
   * ``document.body`` with a dimmed backdrop and an X close button.
   * Used by the project create / edit emoji buttons, which sit too
   * close to the viewport edge for the inline popover positioning to
   * fit. The chat composer keeps the default popover behaviour.
   */
  overlay?: boolean
}

function PickerSkeleton() {
  return (
    <div className="h-[360px] w-[320px] animate-pulse rounded-lg border border-white/8 bg-white/4" />
  )
}

export function EmojiPickerPopover({ onSelect, onClose, recentEmojis, overlay = false }: Props) {
  const { isMobile } = useViewport()
  const messageRecent = useRecentEmojisStore((s) => s.emojis)
  const recent = recentEmojis ?? messageRecent
  const containerRef = useRef<HTMLDivElement>(null)

  // Outside click closes. In overlay mode the backdrop also handles this,
  // but the listener is harmless there — clicks on the backdrop are outside
  // the picker box and so still trigger ``onClose``.
  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (!containerRef.current) return
      if (!containerRef.current.contains(e.target as Node)) onClose()
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [onClose])

  // Escape closes
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const pickerBox = (
    <div
      ref={containerRef}
      className="relative overflow-hidden rounded-lg border border-white/10 bg-[#0f0d16] shadow-xl"
      onClick={overlay ? (e) => e.stopPropagation() : undefined}
    >
      {overlay && (
        <button
          type="button"
          onClick={onClose}
          aria-label="Close emoji picker"
          className="absolute right-1.5 top-1.5 z-10 flex h-6 w-6 items-center justify-center rounded font-mono text-[12px] text-white/55 transition-colors hover:bg-white/10 hover:text-white/85"
        >
          ✕
        </button>
      )}
      <LRUBar emojis={recent} onSelect={onSelect} />
      <Suspense fallback={<PickerSkeleton />}>
        <Picker
          data={loadEmojiData}
          onEmojiSelect={(e: { native: string }) => onSelect(e.native)}
          theme="dark"
          set="native"
          previewPosition="none"
          skinTonePosition="search"
          perLine={isMobile ? 8 : 9}
          categories={['people', 'nature', 'foods', 'activity', 'places', 'objects', 'symbols', 'flags']}
        />
      </Suspense>
    </div>
  )

  if (overlay) {
    return createPortal(
      <>
        {/* Backdrop — sits above any open Sheet (z-50/51). */}
        <div
          className="fixed inset-0 z-[60] bg-black/60"
          onClick={onClose}
          aria-hidden="true"
        />
        {/* Centring wrapper. ``pointer-events-none`` lets clicks fall through
            to the backdrop in the gap between picker and viewport edge; the
            picker box re-enables them with ``pointer-events-auto``. */}
        <div className="pointer-events-none fixed inset-0 z-[61] flex items-center justify-center p-4">
          <div className="pointer-events-auto">{pickerBox}</div>
        </div>
      </>,
      document.body,
    )
  }

  const containerClass = isMobile
    ? 'absolute bottom-full left-0 right-0 mb-2 z-40'
    : 'absolute bottom-full right-0 mb-2 z-40'

  return <div className={containerClass}>{pickerBox}</div>
}
