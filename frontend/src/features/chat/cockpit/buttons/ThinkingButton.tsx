import { useState, useRef, useEffect } from 'react'
import type { ReasoningCapability } from '@/core/types/llm'
import { CockpitButton } from '../CockpitButton'

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

  // Effort initial used as a compact pill — full word would crowd the row.
  const pillLabel =
    active && hasEffort && effort
      ? `Thinking · ${effort[0].toUpperCase()}`
      : active
        ? 'Thinking · on'
        : 'Thinking · off'

  return (
    <div ref={containerRef} className="relative">
      <CockpitButton
        icon="💡"
        state={active ? 'active' : 'idle'}
        accent="gold"
        label={pillLabel}
        onClick={handleClick}
        dataState={active ? 'active' : 'inactive'}
      />
      {popOpen && hasEffort && (
        <ul
          role="menu"
          className="absolute right-0 top-full mt-1 z-40 min-w-[140px] rounded-md border border-white/10 bg-[#0f0d16] py-1 shadow-lg"
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
                aria-checked={active && effort === b}
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
