import { useState, useRef, useEffect } from 'react'
import type { ReasoningCapability } from '@/core/types/llm'
import { CockpitButton } from '../CockpitButton'

// Effort vocabulary -> short badge label. Explicit mapping disambiguates
// "max" from "medium" (both would otherwise abbreviate to "M") and gives
// "xhigh" a stable single-character form. Unknown values fall back to the
// first letter uppercased.
const EFFORT_BADGE: Record<string, string> = {
  low: 'L',
  medium: 'M',
  high: 'H',
  xhigh: 'X',
  max: '+',
}

type Props = {
  reasoning: ReasoningCapability
  mode: 'off' | 'on'
  effort: string | null
  onChange: (mode: 'off' | 'on', effort: string | null) => Promise<void> | void
}

/**
 * Capability-aware Thinking toggle. Pure presentational + local pop-out
 * state — the parent (CockpitBar / ReasoningToolsCluster) owns the source
 * of truth and persists changes via ``onChange``.
 *
 * Five render states, gated by ``reasoning.kind`` and ``reasoning.effort``:
 *   - ``no_reasoning``                          → disabled, "n/a" label
 *   - ``always_on``  (no effort buckets)        → disabled, "always on"
 *   - ``always_on``  (with effort buckets)      → pop-out (Off greyed)
 *   - ``optional``   (no effort buckets)        → simple click toggle
 *   - ``optional``   (with effort buckets)      → pop-out (Off + buckets)
 *
 * Mutex with tools (``exclusive_with_reasoning``) is coordinated one level
 * up — this button just reports its desired mode/effort to ``onChange``.
 */
export function ThinkingButton({ reasoning, mode, effort, onChange }: Props) {
  const [popOpen, setPopOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement | null>(null)

  // Close pop-out on outside click / Escape so a stray click anywhere on the
  // page dismisses it without leaving the menu floating over the chat.
  useEffect(() => {
    if (!popOpen) return
    const onDocClick = (e: MouseEvent) => {
      if (!containerRef.current) return
      if (containerRef.current.contains(e.target as Node)) return
      setPopOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setPopOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [popOpen])

  if (reasoning.kind === 'no_reasoning') {
    return (
      <CockpitButton
        icon="💡"
        state="disabled"
        accent="gold"
        label="Thinking · n/a"
        dataState="inactive"
      />
    )
  }

  // ``always_on`` without effort: nothing for the user to choose.
  if (reasoning.kind === 'always_on' && !reasoning.effort) {
    return (
      <CockpitButton
        icon="💡"
        state="disabled"
        accent="gold"
        label="Thinking · always on"
        dataState="active"
      />
    )
  }

  const hasEffort = reasoning.effort !== null
  const active = mode === 'on'

  const handleClick = () => {
    if (!hasEffort) {
      void onChange(active ? 'off' : 'on', null)
      return
    }
    setPopOpen((v) => !v)
  }

  const handleSelect = (m: 'off' | 'on', e: string | null) => {
    setPopOpen(false)
    void onChange(m, e)
  }

  // Reconcile a stale ``effort`` against the current capability buckets.
  // The session persists the user's last chosen effort across model
  // switches, but a value carried over from a more permissive model
  // (e.g. "max" from DSv4 Pro) may not be in the new model's buckets
  // (e.g. DSv4 Flash on OR exposes only ["high"]). Fall back to the
  // capability's ``default_bucket`` so the badge matches what the
  // backend will actually use after its silent-downgrade. The
  // persisted ``extras.reasoning_effort`` is left untouched, so
  // switching back to the more permissive model restores the user's
  // original choice.
  const effectiveEffort = effort && reasoning.effort?.buckets.includes(effort)
    ? effort
    : reasoning.effort?.default_bucket ?? null

  // Effort initial shown as a small badge in the bottom-right of the button
  // — only when reasoning is on AND a bucket is effective. ``label`` keeps
  // the full word for hover-tooltip + screen readers.
  const effortBadge = active && hasEffort && effectiveEffort
    ? (EFFORT_BADGE[effectiveEffort] ?? effectiveEffort[0].toUpperCase())
    : undefined
  const label = active
    ? hasEffort && effectiveEffort
      ? `Thinking · ${effectiveEffort.charAt(0).toUpperCase() + effectiveEffort.slice(1)}`
      : 'Thinking · on'
    : 'Thinking · off'

  return (
    <div ref={containerRef} className="relative">
      <CockpitButton
        icon="💡"
        state={active ? 'active' : 'idle'}
        accent="gold"
        label={label}
        badge={effortBadge}
        onClick={handleClick}
        dataState={active ? 'active' : 'inactive'}
      />
      {popOpen && hasEffort && (
        <ul
          role="menu"
          className="absolute left-0 bottom-full mb-1 z-40 min-w-[140px] rounded-md border border-white/10 bg-[#0f0d16] py-1 shadow-lg"
        >
          <li>
            <button
              type="button"
              role="menuitemradio"
              aria-checked={!active}
              disabled={reasoning.kind === 'always_on'}
              onClick={() => handleSelect('off', null)}
              className="w-full px-3 py-1.5 text-left text-sm text-white/80 hover:bg-white/5 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Off
            </button>
          </li>
          {reasoning.effort!.buckets.map((b) => (
            <li key={b}>
              <button
                type="button"
                role="menuitemradio"
                aria-checked={active && effectiveEffort === b}
                onClick={() => handleSelect('on', b)}
                className="w-full px-3 py-1.5 text-left text-sm text-white/80 hover:bg-white/5"
              >
                {b[0].toUpperCase() + b.slice(1)}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
