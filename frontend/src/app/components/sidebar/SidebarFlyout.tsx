import { useEffect, type ReactNode } from 'react'

interface SidebarFlyoutProps {
  title: string
  onClose: () => void
  onOpenFullView: () => void
  children: ReactNode
}

export function SidebarFlyout({ title, onClose, onOpenFullView, children }: SidebarFlyoutProps) {
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-30 bg-black/40"
        onClick={onClose}
      />

      {/* Panel */}
      <div className="fixed left-[50px] top-0 z-40 flex h-full w-[260px] flex-col border-r border-white/8 bg-[#1a1a30] shadow-xl">
        {/* Header */}
        <div className="flex flex-shrink-0 items-center justify-between border-b border-white/6 px-4 py-3">
          <span className="text-[12px] font-semibold uppercase tracking-wider text-white/70">
            {title}
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onOpenFullView}
              className="rounded border border-white/10 px-2 py-0.5 text-[10px] text-white/40 transition-colors hover:border-white/20 hover:text-white/60"
            >
              Open full view
            </button>
            <button
              type="button"
              onClick={onClose}
              className="flex h-5 w-5 items-center justify-center rounded text-white/30 transition-colors hover:text-white/60"
            >
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                <path d="M2 2L10 10M10 2L2 10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto [&::-webkit-scrollbar]:w-[3px] [&::-webkit-scrollbar-thumb]:rounded-sm [&::-webkit-scrollbar-thumb]:bg-white/10">
          {children}
        </div>
      </div>
    </>
  )
}
