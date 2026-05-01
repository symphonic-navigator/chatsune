/**
 * Vosk recogniser — local STT for the OFF-state wake phrases.
 *
 * Lifecycle:
 *  - `vosk.init()` — idempotent. First call resolves the model singleton,
 *    constructs `model.KaldiRecognizer(...)` with the constrained grammar,
 *    enables per-word confidence, and wires the result event listener
 *    that runs the match path. State 'idle' → 'loading' → 'ready'.
 *    Subsequent calls when state ∈ {'loading', 'ready'} are no-ops.
 *    A fresh recogniser is built when state is 'idle' (post-dispose) or
 *    'error' (recoverable retry).
 *  - `vosk.feed(pcm)` — pushes audio into the recogniser. Drops silently
 *    when state ≠ 'ready' (Decision #8: no buffering during load), drops
 *    segments > 4 s (CPU guard from VOSK-STT.md). On feed, also calls
 *    retrieveFinalResult() so the recogniser emits a final-result event
 *    instead of waiting for endpointing — our segments are already
 *    end-pointed by the VAD upstream.
 *  - `vosk.dispose()` — calls remove() on the recogniser; the model
 *    singleton in modelLoader survives so re-init within one page-load
 *    is fast.
 *
 * Match flow (inside the result event handler):
 *   { text, result: [{ word, conf, ... }] }
 *     ├─ text not in ACCEPT_TEXTS → drop
 *     ├─ any conf < 0.95 → drop
 *     └─ otherwise → tryDispatchCommand(text)
 *
 * The recogniser is reused across feed calls — re-constructing it would
 * recompile the grammar graph (~2-3 s per call, see VOSK-STT.md
 * performance notes).
 */

import type { KaldiRecognizer, Model } from 'vosk-browser'
import { tryDispatchCommand } from '../dispatcher'
import { ACCEPT_TEXTS, VOSK_GRAMMAR } from './grammar'
import { getModel } from './modelLoader'

type VoskState = 'idle' | 'loading' | 'ready' | 'error'

const SAMPLE_RATE = 16_000
const MAX_SEGMENT_SECONDS = 4
const WAKE_CONF_THRESHOLD = 0.95

let state: VoskState = 'idle'
let recogniser: KaldiRecognizer | null = null

interface VoskResult {
  text: string
  result: Array<{ conf: number; word: string; start?: number; end?: number }>
}

function handleResult(msg: { event: 'result'; result?: VoskResult } | { event: string }): void {
  if (msg.event !== 'result' || !('result' in msg) || !msg.result) return
  const { text, result } = msg.result

  if (!ACCEPT_TEXTS.has(text)) {
    console.debug('[Vosk] rejected (text):', text)
    return
  }

  if (!result.every((w) => w.conf >= WAKE_CONF_THRESHOLD)) {
    console.debug('[Vosk] rejected (conf):', msg.result)
    return
  }

  console.debug('[Vosk] accepted:', text)
  void tryDispatchCommand(text)
}

async function init(): Promise<void> {
  if (state === 'loading' || state === 'ready') return
  state = 'loading'
  try {
    const model = (await getModel()) as Model
    // Aborted while we were waiting for the model — dispose() ran and
    // moved state back to 'idle'. Don't construct a recogniser the
    // caller no longer wants.
    if (state !== 'loading') return
    recogniser = new model.KaldiRecognizer(SAMPLE_RATE, JSON.stringify(VOSK_GRAMMAR))
    recogniser.setWords(true)
    recogniser.on('result', handleResult)
    state = 'ready'
  } catch (err) {
    console.error('[Vosk] init failed:', err)
    state = 'error'
  }
}

function feed(pcm: Float32Array): void {
  if (state !== 'ready' || !recogniser) return

  if (pcm.length / SAMPLE_RATE > MAX_SEGMENT_SECONDS) {
    console.debug('[Vosk] dropping segment > 4 s')
    return
  }

  recogniser.acceptWaveformFloat(pcm, SAMPLE_RATE)
  // VAD has already end-pointed the segment — force the final result so
  // the result listener fires now instead of waiting for the recogniser's
  // own endpointing.
  recogniser.retrieveFinalResult()
}

function dispose(): void {
  if (recogniser) {
    try {
      recogniser.remove()
    } catch (err) {
      console.warn('[Vosk] dispose: remove threw:', err)
    }
    recogniser = null
  }
  state = 'idle'
}

function getState(): VoskState {
  return state
}

export const vosk = { init, feed, dispose, getState }
