import { useCallback } from 'react'
import { useArtefactStore } from '../../core/store/artefactStore'
import { artefactApi } from '../../core/api/artefact'

const TYPE_COLOURS: Record<string, string> = {
  markdown: '180,180,220',
  code: '137,180,250',
  html: '250,170,130',
  svg: '170,220,170',
  jsx: '140,180,250',
  mermaid: '200,170,250',
}

interface ArtefactCardProps {
  handle: string
  title: string
  artefactType: string
  isUpdate: boolean
  sessionId: string
}

export function ArtefactCard({
  handle,
  title,
  artefactType,
  isUpdate,
  sessionId,
}: ArtefactCardProps) {
  const colour = TYPE_COLOURS[artefactType] ?? '180,180,180'

  const handleOpen = useCallback(async () => {
    const store = useArtefactStore.getState()
    const summary = store.artefacts.find((a) => a.handle === handle)
    if (!summary) return
    store.setActiveArtefactLoading(true)
    try {
      const detail = await artefactApi.get(sessionId, summary.id)
      store.openOverlay(detail)
    } catch {
      store.setActiveArtefactLoading(false)
    }
  }, [handle, sessionId])

  return (
    <button
      type="button"
      onClick={handleOpen}
      className="mb-2 flex items-center gap-2.5 rounded-lg px-3 py-2 text-left transition-colors hover:bg-white/[0.03] cursor-pointer"
      style={{
        background: `rgba(${colour},0.05)`,
        border: `1px solid rgba(${colour},0.15)`,
      }}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span
            className="rounded px-1 py-0.5 text-[9px] font-mono uppercase flex-shrink-0"
            style={{ background: `rgba(${colour},0.12)`, color: `rgba(${colour},0.7)` }}
          >
            {artefactType}
          </span>
          <span className="truncate text-[12px] text-white/70">{title}</span>
        </div>
        <span className="text-[10px] font-mono text-white/30 mt-0.5 block">
          {isUpdate ? 'Updated' : 'Created'}: {handle}
        </span>
      </div>
      <span className="flex-shrink-0 text-[10px] font-mono uppercase tracking-wider text-white/25">
        Open
      </span>
    </button>
  )
}
