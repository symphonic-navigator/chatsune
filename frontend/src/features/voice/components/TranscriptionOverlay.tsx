interface TranscriptionOverlayProps {
  text: string
  autoSend: boolean
}

export function TranscriptionOverlay({ text, autoSend }: TranscriptionOverlayProps) {
  if (!text) return null
  return (
    <div className="mx-auto mb-2 max-w-3xl rounded-lg border border-white/10 bg-white/5 px-3 py-2">
      <div className="flex items-center gap-2 mb-1">
        <svg width="12" height="12" viewBox="0 0 14 14" fill="none" className="text-white/40">
          <rect x="5" y="1" width="4" height="8" rx="2" stroke="currentColor" strokeWidth="1.2" />
          <path d="M3 6.5C3 9 5 11 7 11C9 11 11 9 11 6.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
        </svg>
        <span className="text-[10px] uppercase tracking-[0.15em] text-white/40 font-mono">
          {autoSend ? 'Sending...' : 'Transcribed'}
        </span>
      </div>
      <p className="text-[13px] text-white/70">{text}</p>
    </div>
  )
}
