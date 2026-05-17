import type { SeedreamConfig } from '@/core/api/images'
import type { ConfigViewProps } from './registry'

const ASPECTS: SeedreamConfig['aspect'][] = ['1:1', '16:9', '9:16', '4:3', '3:4', '3:2', '2:3']
const QUALITIES: SeedreamConfig['quality'][] = ['standard', 'high', 'ultra']

// Reuse the same primitives shape as the other config views. Kept inline rather
// than extracted to a shared module — three identical SegRow/Stepper copies
// across the three views are cheaper to read than a layer of abstraction.

type SegRowProps<T extends string> = {
  label: string
  options: T[]
  value: T
  onChange: (v: T) => void
}

function SegRow<T extends string>({ label, options, value, onChange }: SegRowProps<T>) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-[11px] text-white/50 shrink-0">{label}</span>
      <div className="flex gap-1 flex-wrap justify-end">
        {options.map((opt) => (
          <button
            key={opt}
            type="button"
            onClick={() => onChange(opt)}
            className={[
              'px-2 py-0.5 rounded text-[11px] font-mono border transition',
              value === opt
                ? 'border-[#c084fc]/60 bg-[#c084fc]/20 text-[#c084fc]'
                : 'border-white/10 bg-white/5 text-white/50 hover:bg-white/10 hover:text-white/75',
            ].join(' ')}
          >
            {opt}
          </button>
        ))}
      </div>
    </div>
  )
}

type StepperProps = {
  label: string
  value: number
  min: number
  max: number
  onChange: (v: number) => void
}

function Stepper({ label, value, min, max, onChange }: StepperProps) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-[11px] text-white/50 shrink-0">{label}</span>
      <div className="flex items-center gap-1">
        <button
          type="button"
          disabled={value <= min}
          onClick={() => onChange(Math.max(min, value - 1))}
          className="w-6 h-6 flex items-center justify-center rounded border border-white/10 bg-white/5 text-white/60 hover:bg-white/15 disabled:opacity-30 disabled:cursor-not-allowed text-sm leading-none transition"
          aria-label="Decrease"
        >
          −
        </button>
        <span className="w-5 text-center text-[12px] font-mono text-white/85">{value}</span>
        <button
          type="button"
          disabled={value >= max}
          onClick={() => onChange(Math.min(max, value + 1))}
          className="w-6 h-6 flex items-center justify-center rounded border border-white/10 bg-white/5 text-white/60 hover:bg-white/15 disabled:opacity-30 disabled:cursor-not-allowed text-sm leading-none transition"
          aria-label="Increase"
        >
          +
        </button>
      </div>
    </div>
  )
}

// --- public view -------------------------------------------------------------

export function SeedreamConfigView({ config, onChange }: ConfigViewProps<SeedreamConfig>) {
  return (
    <div className="space-y-2">
      <SegRow
        label="Aspect"
        options={ASPECTS}
        value={config.aspect}
        onChange={(aspect) => onChange({ ...config, aspect })}
      />
      <SegRow
        label="Quality"
        options={QUALITIES}
        value={config.quality}
        onChange={(quality) => onChange({ ...config, quality })}
      />
      <Stepper
        label="Count"
        value={config.n}
        min={1}
        max={4}
        onChange={(n) => onChange({ ...config, n })}
      />
    </div>
  )
}
