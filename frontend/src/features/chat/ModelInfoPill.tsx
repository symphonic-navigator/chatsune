import { useEffect, useState } from 'react'
import { llmApi } from '../../core/api/llm'
import type { ModelMetaDto } from '../../core/types/llm'
import type { PersonaDto } from '../../core/types/persona'
import { useViewport } from '../../core/hooks/useViewport'

interface ModelInfoPillProps {
  persona: PersonaDto | null
}

/**
 * Compact pill showing the active model's slug, with a hover popover that
 * exposes provider, size, quantisation, and context window.
 *
 * Self-contained — fetches `listConnectionModels` for the persona's connection
 * whenever the persona's `model_unique_id` changes.
 */
export function ModelInfoPill({ persona }: ModelInfoPillProps) {
  const { isMobile } = useViewport()
  const [open, setOpen] = useState(false)
  const [model, setModel] = useState<ModelMetaDto | null>(null)

  const uid = persona?.model_unique_id ?? null
  const [connectionId, modelSlug] = uid && uid.includes(':')
    ? [uid.split(':')[0], uid.split(':').slice(1).join(':')]
    : [null, null]

  useEffect(() => {
    if (!connectionId || !modelSlug) {
      setModel(null)
      return
    }
    let cancelled = false
    llmApi
      .listConnectionModels(connectionId)
      .then((models) => {
        if (cancelled) return
        const found = models.find((m) => m.model_id === modelSlug) ?? null
        setModel(found)
      })
      .catch(() => {
        if (cancelled) return
        setModel(null)
      })
    return () => { cancelled = true }
  }, [connectionId, modelSlug])

  if (!uid || !modelSlug) return null

  // On mobile we keep things simple — no tooltip at all.
  const interactionProps = isMobile
    ? {}
    : { onMouseEnter: () => setOpen(true), onMouseLeave: () => setOpen(false) }

  const showTooltip = !isMobile && open && model

  return (
    <span className="relative inline-flex" {...interactionProps}>
      <span
        className="flex items-center rounded-full border border-white/10 bg-white/3 px-2 py-0.5 font-mono text-[11px] text-white/40 cursor-default"
      >
        {modelSlug}
      </span>
      {showTooltip && (
        <div
          role="tooltip"
          className="absolute right-0 top-full mt-2 z-50 w-72 rounded-md border border-white/15 bg-[#0b0a08] lg:bg-[#0b0a08]/95 lg:backdrop-blur-sm shadow-sm lg:shadow-[0_8px_24px_rgba(0,0,0,0.5)] px-3 py-2.5 text-[12px] text-white/70 font-mono leading-relaxed"
        >
          <Row label="Provider" value={model.connection_display_name} />
          <Row label="Model" value={model.model_id} />
          {model.parameter_count && <Row label="Size" value={model.parameter_count} />}
          {model.quantisation_level && <Row label="Quant" value={model.quantisation_level} />}
          {model.context_window > 0 && (
            <Row label="Context" value={`${model.context_window.toLocaleString()} tokens`} />
          )}
        </div>
      )}
    </span>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-white/40">{label}</span>
      <span className="text-white/85 truncate">{value}</span>
    </div>
  )
}
