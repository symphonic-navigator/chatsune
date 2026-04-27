interface MobileSidebarHeaderProps {
  /** When set, the header is in overlay mode showing back-arrow + title. */
  title?: string
  /** Required when title is set — handles back-navigation to main view. */
  onBack?: () => void
  /** Always required — closes the entire mobile drawer. */
  onClose: () => void
}

export function MobileSidebarHeader({ title, onBack, onClose }: MobileSidebarHeaderProps) {
  const isOverlay = title !== undefined

  return (
    <div className="flex h-[50px] flex-shrink-0 items-center gap-1 border-b border-white/5 px-3.5">
      {isOverlay ? (
        <button
          type="button"
          onClick={onBack}
          aria-label="Back to main"
          className="flex flex-1 min-h-[44px] items-center gap-2.5 rounded-md -mx-1 px-1 py-0.5 text-left transition-colors hover:bg-white/5"
        >
          <span className="text-[18px] text-white/60">‹</span>
          <span className="flex-1 text-[15px] font-semibold tracking-wide text-white/85">{title}</span>
        </button>
      ) : (
        <button
          type="button"
          onClick={onClose}
          aria-label="Close sidebar"
          className="flex flex-1 min-h-[44px] items-center gap-2.5 rounded-md -mx-1 px-1 py-0.5 text-left transition-colors hover:bg-white/5"
        >
          <span className="text-[17px]">🦊</span>
          <span className="flex-1 text-[15px] font-semibold tracking-wide text-white/85">Chatsune</span>
        </button>
      )}

      <button
        type="button"
        onClick={onClose}
        aria-label="Close drawer"
        className="flex h-7 w-7 items-center justify-center rounded text-[14px] text-white/60 transition-colors hover:bg-white/8 hover:text-white/85"
      >
        ✕
      </button>
    </div>
  )
}
