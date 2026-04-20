import { CAPABILITY_META } from '../../../core/types/providers'
import type { Capability } from '../../../core/types/providers'

interface CoverageRowProps {
  covered: Set<string>
  providersByCapability: Map<string, string[]>
}

const ALL: Capability[] = ['llm', 'tts', 'stt', 'websearch', 'tti', 'iti']

export function CoverageRow({ covered, providersByCapability }: CoverageRowProps) {
  return (
    <div className="flex flex-wrap gap-2 px-6 py-4 border-b border-white/8">
      {ALL.map((cap) => {
        const isCovered = covered.has(cap)
        const meta = CAPABILITY_META[cap]
        const providers = providersByCapability.get(cap) ?? []
        const tip = isCovered && providers.length > 0
          ? `${meta.tooltip}\n\nProvided by: ${providers.join(', ')}`
          : meta.tooltip
        return (
          <span
            key={cap}
            data-capability={cap}
            data-covered={isCovered ? 'true' : 'false'}
            title={tip}
            className={[
              'inline-flex items-center rounded-full px-3 py-1 text-[11px] font-mono',
              isCovered
                ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30'
                : 'bg-white/5 text-white/30 border border-white/10',
            ].join(' ')}
          >
            {meta.label}
          </span>
        )
      })}
    </div>
  )
}
