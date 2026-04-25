interface Props {
  emojis: string[]
  onSelect: (emoji: string) => void
}

export function LRUBar({ emojis, onSelect }: Props) {
  if (emojis.length === 0) return null
  return (
    <div className="flex items-center gap-1 rounded-t-lg border-b border-white/8 bg-[#1a1625] px-2 py-1.5">
      <span className="mr-2 text-[10px] uppercase tracking-wider text-white/40">
        Recent
      </span>
      {emojis.map((emoji) => (
        <button
          key={emoji}
          type="button"
          onClick={() => onSelect(emoji)}
          aria-label={`Insert ${emoji}`}
          className="rounded-md px-1.5 py-0.5 text-lg transition-colors hover:bg-white/10"
        >
          {emoji}
        </button>
      ))}
    </div>
  )
}
