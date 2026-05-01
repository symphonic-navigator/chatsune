/**
 * Tone cues for voice-command responses.
 *
 * Audio vocabulary: at most two notes per cue, two-octave range, square-wave
 * through a swept lowpass — the "signature" sound the rest of the command
 * system inherits. New cues added later (errors etc.) must respect this
 * shape.
 *
 * Implementation lifted from the STATE-CUE.md spike. Uses its own
 * AudioContext, completely separate from the persona TTS pipeline and the
 * audioCapture VAD context. Lazy-initialised on first call; the user-gesture
 * requirement is met cooperatively because cues only fire after a
 * user-initiated continuous-voice start.
 */

const NOTES = { C4: 261.63, G3: 196.00, G4: 392.00 } as const

const CUE_OPTS = {
  waveform: 'square' as const,
  /** Master gain (0–1). 0.30 is the STATE-CUE.md default — comfortable next to persona TTS. */
  volume: 0.30,
  /** Exponential lowpass sweep: bright attack opening, dark resolved tail. */
  filter: { startHz: 7000, endHz: 300, Q: 1 },
  /** Gain envelope ramps. Below ~5 ms = audible click; above ~30 ms = mushy attack. */
  envelopeMs: 12,
  /** Silence between notes in a sequence. */
  gapMs: 30,
} as const

let ctx: AudioContext | null = null

function audio(): AudioContext {
  if (!ctx) ctx = new AudioContext()
  // iOS Safari + background tabs may park the context in 'suspended'.
  // Calling resume() each entry is cheap and idempotent.
  if (ctx.state === 'suspended') void ctx.resume()
  return ctx
}

function scheduleBlip(startAt: number, freq: number, durationMs: number): void {
  const c = audio()
  const osc = c.createOscillator()
  const filter = c.createBiquadFilter()
  const gain = c.createGain()

  osc.type = CUE_OPTS.waveform
  osc.frequency.setValueAtTime(freq, startAt)

  filter.type = 'lowpass'
  filter.Q.setValueAtTime(CUE_OPTS.filter.Q, startAt)
  filter.frequency.setValueAtTime(CUE_OPTS.filter.startHz, startAt)
  filter.frequency.exponentialRampToValueAtTime(
    CUE_OPTS.filter.endHz,
    startAt + durationMs / 1000,
  )

  // Linear envelope: ramp up to volume, hold, ramp down to silence.
  // Cap envelope segment at duration/4 so very short notes stay clean.
  const envSec = Math.min(CUE_OPTS.envelopeMs, durationMs / 4) / 1000
  const endSec = startAt + durationMs / 1000
  gain.gain.setValueAtTime(0, startAt)
  gain.gain.linearRampToValueAtTime(CUE_OPTS.volume, startAt + envSec)
  gain.gain.linearRampToValueAtTime(CUE_OPTS.volume, endSec - envSec)
  gain.gain.linearRampToValueAtTime(0, endSec)

  osc.connect(filter).connect(gain).connect(c.destination)
  osc.start(startAt)
  osc.stop(endSec + 0.01)
}

function playSequence(notes: ReadonlyArray<readonly [number, number]>): void {
  const c = audio()
  let t = c.currentTime
  for (const [freq, durMs] of notes) {
    scheduleBlip(t, freq, durMs)
    t += durMs / 1000 + CUE_OPTS.gapMs / 1000
  }
}

import type { CueKind } from './types'
export type { CueKind }

export function playCue(kind: CueKind): void {
  switch (kind) {
    case 'on':
      // Ascending perfect fifth — Bluetooth-style "connect" pattern.
      return playSequence([[NOTES.C4, 130], [NOTES.G4, 80]])
    case 'off':
      // Descending perfect fifth — mirror of 'on', "disconnect" pattern.
      return playSequence([[NOTES.G4, 130], [NOTES.C4, 80]])
    case 'error':
      // Flat repeated low G — no interval movement signals "input not recognised",
      // distinct from both ascending/descending fifth cues.
      return playSequence([[NOTES.G3, 130], [NOTES.G3, 80]])
  }
}
