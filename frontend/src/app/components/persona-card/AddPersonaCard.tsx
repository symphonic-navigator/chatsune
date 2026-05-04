import React from "react"

interface AddPersonaCardProps {
  onCreateNew: () => void
  onImport: () => void
  index: number
}

const HALF_BASE = "relative flex flex-1 flex-col items-center justify-center gap-2 cursor-pointer transition-colors group"
const ICON_BG = "rgba(201,168,76,0.04)"
const BORDER_COLOUR = "rgba(201,168,76,0.3)"
const LABEL_COLOUR = "rgba(201,168,76,0.45)"
const HOVER_BG = "rgba(201,168,76,0.04)"

export default function AddPersonaCard({ onCreateNew, onImport, index }: AddPersonaCardProps) {
  const cardStyle: React.CSSProperties = {
    width: "clamp(160px, 42vw, 210px)",
    height: "clamp(240px, 63vw, 320px)",
    border: "1px dashed rgba(201,168,76,0.15)",
    animation: `card-entrance 0.6s cubic-bezier(0.16, 1, 0.3, 1) ${index * 0.1}s both`,
  }

  return (
    <div
      style={cardStyle}
      className="relative flex flex-col rounded-xl bg-transparent overflow-hidden hover:border-[rgba(201,168,76,0.35)]"
    >
      {/* Top half: Create new */}
      <button
        type="button"
        aria-label="Create new persona"
        onClick={onCreateNew}
        className={HALF_BASE}
        style={{ background: 'transparent' }}
        onMouseEnter={(e) => (e.currentTarget.style.background = HOVER_BG)}
        onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
      >
        <div
          className="w-9 h-9 rounded-full flex items-center justify-center"
          style={{ border: `1px dashed ${BORDER_COLOUR}`, color: LABEL_COLOUR, background: ICON_BG }}
        >
          <svg width="16" height="16" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <line x1="9" y1="3" x2="9" y2="15" />
            <line x1="3" y1="9" x2="15" y2="9" />
          </svg>
        </div>
        <span
          className="font-mono text-[10px] uppercase tracking-widest"
          style={{ color: LABEL_COLOUR }}
        >
          add persona
        </span>
      </button>

      {/* Divider */}
      <div className="h-px" style={{ background: "rgba(201,168,76,0.15)" }} aria-hidden="true" />

      {/* Bottom half: Import */}
      <button
        type="button"
        aria-label="Import persona from file"
        onClick={onImport}
        className={HALF_BASE}
        style={{ background: 'transparent' }}
        onMouseEnter={(e) => (e.currentTarget.style.background = HOVER_BG)}
        onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
      >
        <div
          className="w-9 h-9 rounded-full flex items-center justify-center"
          style={{ border: `1px dashed ${BORDER_COLOUR}`, color: LABEL_COLOUR, background: ICON_BG }}
        >
          {/* Down-arrow into a tray icon */}
          <svg width="16" height="16" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M9 3v8" />
            <path d="M5 7l4 4 4-4" />
            <path d="M3 14h12" />
          </svg>
        </div>
        <span
          className="font-mono text-[10px] uppercase tracking-widest"
          style={{ color: LABEL_COLOUR }}
        >
          import from file
        </span>
      </button>
    </div>
  )
}
