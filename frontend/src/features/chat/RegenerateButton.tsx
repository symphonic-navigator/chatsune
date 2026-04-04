interface RegenerateButtonProps { onClick: () => void; disabled: boolean }

export function RegenerateButton({ onClick, disabled }: RegenerateButtonProps) {
  return (
    <button type="button" onClick={onClick} disabled={disabled}
      className="mt-1 flex items-center gap-1.5 rounded-full border border-white/8 bg-white/3 px-3 py-1 text-[12px] text-white/30 transition-colors hover:bg-white/6 hover:text-white/50 disabled:opacity-30">
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
        <path d="M1 6C1 3.24 3.24 1 6 1C8.76 1 11 3.24 11 6C11 8.76 8.76 11 6 11" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
        <path d="M1 6L3 4M1 6L3 8" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      Regenerate
    </button>
  )
}
