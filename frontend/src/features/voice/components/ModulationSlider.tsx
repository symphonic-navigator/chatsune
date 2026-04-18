import type { ChakraPaletteEntry } from '../../../core/types/chakra'

interface Props {
  label: string
  value: number
  min: number
  max: number
  step: number
  format: (v: number) => string
  chakra: ChakraPaletteEntry
  onChange: (v: number) => void
}

export function ModulationSlider({ label, value, min, max, step, format, chakra, onChange }: Props) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-16 text-[10px] uppercase tracking-[0.15em] text-white/50 font-mono">
        {label}
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number.parseFloat(e.target.value))}
        className="flex-1 h-1 appearance-none bg-white/10 rounded-full cursor-pointer accent-current"
        style={{ color: chakra.hex }}
      />
      <span className="w-12 text-right text-[11px] font-mono text-white/70 tabular-nums">
        {format(value)}
      </span>
    </div>
  )
}
