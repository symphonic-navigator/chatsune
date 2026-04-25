import type { CSSProperties } from "react"
import type { RefreshFrequency } from "../../core/types/knowledge"

export type { RefreshFrequency }

interface Props {
  /** Current value. `null` means inherit (only valid when `inheritFrom` is provided). */
  value: RefreshFrequency | null
  onChange: (next: RefreshFrequency | null) => void
  /** When given, allow a "(inherit: X)" option that maps to value=null. */
  inheritFrom?: RefreshFrequency
  disabled?: boolean
  label?: string
}

const OPTION_STYLE: CSSProperties = {
  background: "#0f0d16",
  color: "rgba(255,255,255,0.85)",
}

const LABELS: Record<RefreshFrequency, string> = {
  rarely: "Rarely (every 10+ messages)",
  standard: "Standard (every 7+ messages)",
  often: "Often (every 5+ messages)",
}

export function RefreshFrequencySelect({
  value,
  onChange,
  inheritFrom,
  disabled,
  label,
}: Props) {
  const selectValue = value === null ? "__inherit__" : value
  return (
    <label className="flex flex-col gap-1 text-sm">
      {label && <span className="text-white/70">{label}</span>}
      <select
        value={selectValue}
        disabled={disabled}
        onChange={(e) => {
          const v = e.target.value
          onChange(v === "__inherit__" ? null : (v as RefreshFrequency))
        }}
        className="rounded border border-white/10 bg-transparent px-3 py-2 text-sm outline-none focus:border-gold/60"
      >
        {inheritFrom && (
          <option value="__inherit__" style={OPTION_STYLE}>
            Inherit ({LABELS[inheritFrom].split(" ")[0]})
          </option>
        )}
        {(["rarely", "standard", "often"] as const).map((k) => (
          <option key={k} value={k} style={OPTION_STYLE}>
            {LABELS[k]}
          </option>
        ))}
      </select>
    </label>
  )
}
