import type { ReactNode } from 'react'
import { useBargeSettingsStore } from '@/features/voice/stores/bargeSettingsStore'
import { usePhase } from '@/features/voice/usePhase'

/**
 * Toggle button for the barging preference. Visible in the cockpit
 * only while live voice mode is active (sibling components decide
 * the visibility — this component renders unconditionally when
 * mounted).
 *
 * Three visual states:
 *   - on:                open-lips, green, no pulse
 *   - off + not speaking: lips-with-slash, red, no pulse
 *   - off + speaking:     mic-with-slash, red, slow pulse ('Sendepause')
 *
 * The mic-with-slash glyph during persona speech is the explicit cue
 * that the user's voice input is currently being held back. The
 * glyph swap (lips → mic) makes the cue semantically direct without
 * adding a second slash to the existing blue VoiceButton.
 *
 * See devdocs/specs/2026-05-07-barging-toggle-design.md.
 */
export function BargingToggleButton() {
  const enabled = useBargeSettingsStore((s) => s.enabled)
  const toggle = useBargeSettingsStore((s) => s.toggle)
  const phase = usePhase()

  const isSpeaking = phase === 'speaking'

  let state: 'on' | 'off-idle' | 'off-speaking'
  let glyph: ReactNode
  let title: string

  if (enabled) {
    state = 'on'
    glyph = <LipsOpenIcon />
    title = 'You can interrupt the persona while she speaks'
  } else if (isSpeaking) {
    state = 'off-speaking'
    glyph = <MicSlashIcon />
    title = "Mic asleep while persona speaks — tap to enable"
  } else {
    state = 'off-idle'
    glyph = <LipsSlashIcon />
    title = "Persona speech can't be interrupted — tap to enable"
  }

  const colourClass = enabled
    ? 'text-[#4ade80] border-[#22c55e]/35 bg-[#22c55e]/15'
    : 'text-[#ef4444] border-[#dc2626]/35 bg-[#dc2626]/15'

  const pulseClass = state === 'off-speaking' ? 'animate-pulse-slow' : ''

  const className = [
    'cockpit-btn-fixed inline-flex items-center justify-center rounded-md border transition',
    colourClass,
    pulseClass,
  ].filter(Boolean).join(' ')

  return (
    <button
      type="button"
      onClick={toggle}
      title={title}
      aria-label={title}
      aria-pressed={!enabled}
      data-barge-state={state}
      className={className}
    >
      {glyph}
    </button>
  )
}

function LipsOpenIcon() {
  return (
    <svg
      data-glyph="lips-open"
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <ellipse cx="8" cy="8" rx="5" ry="2.6" />
      <path d="M3 8H13" strokeWidth="1.1" opacity="0.55" />
    </svg>
  )
}

function LipsSlashIcon() {
  return (
    <svg
      data-glyph="lips-slash"
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <ellipse cx="8" cy="8" rx="5" ry="2.6" />
      <path d="M3 8H13" strokeWidth="1.1" opacity="0.55" />
      <path d="M2 14 L14 2" strokeWidth="1.6" />
    </svg>
  )
}

function MicSlashIcon() {
  return (
    <svg
      data-glyph="mic-slash"
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden="true"
    >
      <rect x="6" y="2" width="4" height="7" rx="2" fill="currentColor" />
      <path
        d="M4 7.5V8a4 4 0 0 0 8 0v-.5"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
      />
      <path d="M8 12v2" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
      <path d="M5.5 14h5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
      <path
        d="M2 2 14 14"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  )
}
