import { Suspense, lazy, useEffect, useRef } from 'react'
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
}

function PickerSkeleton() {
  return (
    <div className="h-[360px] w-[320px] animate-pulse rounded-lg border border-white/8 bg-white/4" />
  )
}

export function EmojiPickerPopover({ onSelect, onClose, recentEmojis }: Props) {
  const { isMobile } = useViewport()
  const messageRecent = useRecentEmojisStore((s) => s.emojis)
  const recent = recentEmojis ?? messageRecent
  const containerRef = useRef<HTMLDivElement>(null)

  // Outside click closes
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

  const containerClass = isMobile
    ? 'absolute bottom-full left-0 right-0 mb-2 z-40'
    : 'absolute bottom-full right-0 mb-2 z-40'

  return (
    <div ref={containerRef} className={containerClass}>
      <div className="overflow-hidden rounded-lg border border-white/10 bg-[#0f0d16] shadow-xl">
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
    </div>
  )
}
