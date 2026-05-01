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
  console.info('[Vosk] event:', msg.event, msg)
  if (msg.event !== 'result' || !('result' in msg) || !msg.result) return
  const { text, result } = msg.result

  if (!ACCEPT_TEXTS.has(text)) {
    console.info('[Vosk] rejected (text):', JSON.stringify(text), '— not in accept set')
    return
  }

  const failingWord = result.find((w) => w.conf < WAKE_CONF_THRESHOLD)
  if (failingWord) {
    console.info('[Vosk] rejected (conf): word=%s conf=%s threshold=%s — full result:', failingWord.word, failingWord.conf, WAKE_CONF_THRESHOLD, msg.result)
    return
  }

  console.info('[Vosk] ACCEPTED:', text, '— dispatching')
  void tryDispatchCommand(text)
}

async function init(): Promise<void> {
  if (state === 'loading' || state === 'ready') {
    console.info('[Vosk] init: already', state, '— skipping')
    return
  }
  console.info('[Vosk] init starting (state was %s)', state)
  state = 'loading'
  try {
    const model = (await getModel()) as Model
    // Aborted while we were waiting for the model — dispose() ran and
    // moved state back to 'idle'. Don't construct a recogniser the
    // caller no longer wants.
    if (state !== 'loading') {
      console.info('[Vosk] init: aborted during model load (state=%s)', state)
      return
    }
    recogniser = new model.KaldiRecognizer(SAMPLE_RATE, JSON.stringify(VOSK_GRAMMAR))
    recogniser.setWords(true)
    recogniser.on('result', handleResult)
    state = 'ready'
    console.info('[Vosk] init: READY — recogniser constructed with grammar (%d entries)', VOSK_GRAMMAR.length)
  } catch (err) {
    console.error('[Vosk] init FAILED:', err)
    state = 'error'
  }
}

function feed(pcm: Float32Array): void {
  if (state !== 'ready' || !recogniser) {
    console.info('[Vosk] feed: SKIPPED (state=%s, samples=%d)', state, pcm.length)
    return
  }

  const seconds = pcm.length / SAMPLE_RATE
  if (seconds > MAX_SEGMENT_SECONDS) {
    console.info('[Vosk] feed: dropping segment > 4 s (%s s, %d samples)', seconds.toFixed(2), pcm.length)
    return
  }

  console.info('[Vosk] feed: %d samples (%s s) → acceptWaveformFloat + retrieveFinalResult', pcm.length, seconds.toFixed(2))
  recogniser.acceptWaveformFloat(pcm, SAMPLE_RATE)
  // VAD has already end-pointed the segment — force the final result so
  // the result listener fires now instead of waiting for the recogniser's
  // own endpointing.
  recogniser.retrieveFinalResult()
}

function dispose(): void {
  console.info('[Vosk] dispose (state was %s)', state)
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
