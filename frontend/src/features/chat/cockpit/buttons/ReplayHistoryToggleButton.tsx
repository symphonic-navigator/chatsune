import { useEffect, useRef, useState } from 'react'
import { CockpitButton } from '../CockpitButton'
import { useCockpitSession, useCockpitStore } from '../cockpitStore'

type Props = {
  sessionId: string
}

// Mini-hint shown for 3 seconds after the toggle changes state to
// communicate the non-retroactive semantics (per INS-049).
const HINT_TEXT = 'Applies from next response'
const HINT_DURATION_MS = 3000

/**
 * Cockpit toggle for ``extras.replay_tool_history``. The flag governs
 * whether past tool-call narration is re-injected as
 * assistant(tool_calls) + tool(result) triplets on the next turn. See
 * spec ``devdocs/specs/2026-05-17-replay-tool-history-toggle-ui-design.md``
 * and INS-049 for the per-turn-snapshot semantic that makes the toggle
 * non-retroactive.
 *
 * Shape and state semantics mirror ``ThinkingButton``: a single
 * ``CockpitButton`` rendered through the accent palette, ``active``
 * when on, ``idle`` when off. After every state change a transient
 * hint surfaces below the button for 3 seconds before fading out, so
 * the "applies from next response" semantic does not need permanent
 * UI real estate.
 */
export function ReplayHistoryToggleButton({ sessionId }: Props) {
  const cockpit = useCockpitSession(sessionId)
  const updateExtras = useCockpitStore((s) => s.updateExtras)
  // ``true`` is the on-disk default — a freshly-hydrated session or
  // pre-feature stored extras render the toggle in the active state.
  const enabled = cockpit?.extras.replay_tool_history ?? true

  const [hintVisible, setHintVisible] = useState(false)
  const timeoutRef = useRef<number | null>(null)

  useEffect(() => () => {
    if (timeoutRef.current !== null) {
      window.clearTimeout(timeoutRef.current)
    }
  }, [])

  const handleClick = async () => {
    // Surface the hint before issuing the patch so the user gets
    // immediate feedback; rolling back the optimistic state on a
    // server rejection still hides the hint via the auto-clear.
    if (timeoutRef.current !== null) {
      window.clearTimeout(timeoutRef.current)
    }
    setHintVisible(true)
    timeoutRef.current = window.setTimeout(() => {
      setHintVisible(false)
      timeoutRef.current = null
    }, HINT_DURATION_MS)

    await updateExtras(sessionId, { replay_tool_history: !enabled })
  }

  const label = enabled
    ? 'Tool history replay: on'
    : 'Tool history replay: off'

  return (
    <div className="relative" data-replay-toggle-state={enabled ? 'on' : 'off'}>
      <CockpitButton
        icon="↻"
        state={enabled ? 'active' : 'idle'}
        accent="gold"
        label={label}
        ariaLabel={label}
        onClick={() => {
          void handleClick()
        }}
        dataState={enabled ? 'active' : 'inactive'}
      />
      {hintVisible && (
        <div
          role="status"
          aria-live="polite"
          className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 whitespace-nowrap rounded-md border border-white/10 bg-[#1a1625] px-2 py-1 text-[11px] text-white/80 shadow-lg motion-reduce:transition-none transition-opacity"
        >
          {HINT_TEXT}
        </div>
      )}
    </div>
  )
}
