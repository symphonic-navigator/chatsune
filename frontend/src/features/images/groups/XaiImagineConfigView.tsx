import type { XaiImagineConfig } from '@/core/api/images'
import type { ConfigViewProps } from './registry'

const TIERS: XaiImagineConfig['tier'][] = ['normal', 'pro']
const RESOLUTIONS: XaiImagineConfig['resolution'][] = ['1k', '2k']
const ASPECTS: XaiImagineConfig['aspect'][] = ['1:1', '16:9', '9:16', '4:3', '3:4']

// --- internal primitives -----------------------------------------------------

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
      <div className="flex gap-1">
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

export function XaiImagineConfigView({ config, onChange }: ConfigViewProps<XaiImagineConfig>) {
  return (
    <div className="space-y-2">
      <SegRow
        label="Tier"
        options={TIERS}
        value={config.tier}
        onChange={(tier) => onChange({ ...config, tier })}
      />
      <SegRow
        label="Resolution"
        options={RESOLUTIONS}
        value={config.resolution}
        onChange={(resolution) => onChange({ ...config, resolution })}
      />
      <SegRow
        label="Aspect"
        options={ASPECTS}
        value={config.aspect}
        onChange={(aspect) => onChange({ ...config, aspect })}
      />
      <Stepper
        label="Count"
        value={config.n}
        min={1}
        max={10}
        onChange={(n) => onChange({ ...config, n })}
      />
    </div>
  )
}
