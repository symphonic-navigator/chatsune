import type { ZImageConfig } from '@/core/api/images'
import type { ConfigViewProps } from './registry'

const MODELS: ZImageConfig['model'][] = ['turbo', 'base']
const SIZES: ZImageConfig['size'][] = [
  '256x256',
  '512x512',
  '768x768',
  '1024x1024',
  '1280x720',
  '720x1280',
  '1536x1024',
  '1024x1536',
  '1536x1536',
]

/** Option style applied to native <select> options — see CLAUDE.md. */
const OPTION_STYLE: React.CSSProperties = {
  background: '#0f0d16',
  color: 'rgba(255,255,255,0.85)',
}

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

export function ZImageConfigView({ config, onChange }: ConfigViewProps<ZImageConfig>) {
  // Base is ~10× slower than Turbo; the backend caps n at 4 for Base. Mirror
  // that cap in the UI so the Stepper doesn't let users dial in a value the
  // server will silently clamp.
  const nMax = config.model === 'base' ? 4 : 10
  const clampedN = Math.min(config.n, nMax)

  return (
    <div className="space-y-2">
      <SegRow
        label="Model"
        options={MODELS}
        value={config.model}
        onChange={(model) => {
          const nextN = model === 'base' ? Math.min(config.n, 4) : config.n
          onChange({ ...config, model, n: nextN })
        }}
      />
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] text-white/50 shrink-0">Size</span>
        <select
          value={config.size}
          onChange={(e) => onChange({ ...config, size: e.target.value as ZImageConfig['size'] })}
          className="text-[11px] bg-[#1a1625] border border-white/15 rounded px-2 py-1 text-white/85 focus:outline-none focus:border-[#c084fc]/50 font-mono"
        >
          {SIZES.map((s) => (
            <option key={s} value={s} style={OPTION_STYLE}>{s}</option>
          ))}
        </select>
      </div>
      <Stepper
        label="Count"
        value={clampedN}
        min={1}
        max={nMax}
        onChange={(n) => onChange({ ...config, n })}
      />
    </div>
  )
}
