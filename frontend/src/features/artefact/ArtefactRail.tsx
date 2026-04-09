import { useArtefactStore } from '../../core/store/artefactStore'

export function ArtefactRail() {
  const count = useArtefactStore((s) => s.artefacts.length)
  const toggleSidebar = useArtefactStore((s) => s.toggleSidebar)

  if (count === 0) return null

  return (
    <button
      type="button"
      onClick={toggleSidebar}
      className="hidden lg:flex w-10 flex-shrink-0 flex-col items-center gap-2 border-l border-white/6 bg-white/[0.01] pt-4 transition-colors hover:bg-white/[0.03] cursor-pointer"
      title="Toggle artefact panel"
    >
      <svg width="10" height="10" viewBox="0 0 10 10" fill="none" className="text-gold/60">
        <path d="M6 1L2 5L6 9" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <span className="rounded-full bg-gold/15 px-1.5 py-0.5 text-[10px] font-mono text-gold/80">
        {count}
      </span>
    </button>
  )
}
