/**
 * Vosk recogniser — local STT for the OFF-state wake phrases.
 *
 * Lifecycle:
 *  - `vosk.init()` — idempotent. First call loads the model + builds a
 *    KaldiRecognizer with the constrained grammar. State 'idle' → 'loading'
 *    → 'ready'. Subsequent calls when state ∈ {'loading', 'ready'} are
 *    no-ops; a fresh recogniser is built when state is 'idle' (post-dispose)
 *    or 'error' (recoverable retry).
 *  - `vosk.feed(pcm)` — synchronous from the caller's perspective. Drops
 *    silently when state ≠ 'ready' (Decision #8: no buffering during load),
 *    drops segments > 4 s (CPU guard), runs the recogniser otherwise.
 *  - `vosk.dispose()` — frees the recogniser; model singleton survives so
 *    re-init within one page-load is fast. Use at continuous-voice stop.
 *
 * Match flow (inside feed):
 *   acceptWaveform → finalResult { text, result: [{word, conf}, ...] }
 *     ├─ text not in ACCEPT_TEXTS → drop
 *     ├─ any conf < 0.95 → drop
 *     └─ otherwise → tryDispatchCommand(text)
 *
 * Recogniser is reused across calls — fresh KaldiRecognizer per feed
 * would recompile the grammar graph every time (~2-3 s wasted per call,
 * see VOSK-STT.md performance notes).
 *
 * vosk-browser 0.0.8 type note: `KaldiRecognizer` is a type alias plus a
 * nested constructor exposed via `Model.KaldiRecognizer`. The test suite
 * mocks the package with a top-level `KaldiRecognizer` named export, so
 * we read the constructor via namespace import + index access — that
 * works against both the test mock and (when narrowed to the actual
 * shape) the real package, without violating `verbatimModuleSyntax`.
 */

import * as voskBrowser from 'vosk-browser'
import { tryDispatchCommand } from '../dispatcher'
import { ACCEPT_TEXTS, VOSK_GRAMMAR } from './grammar'
import { getModel } from './modelLoader'

type VoskState = 'idle' | 'loading' | 'ready' | 'error'

const SAMPLE_RATE = 16_000
const MAX_SEGMENT_SECONDS = 4
const WAKE_CONF_THRESHOLD = 0.95

interface FinalResult {
  text: string
  result: Array<{ word: string; conf: number }>
}

interface RecogniserHandle {
  acceptWaveform: (pcm: Float32Array) => unknown
  finalResult: () => FinalResult
  remove: () => void
}

type KaldiRecognizerCtor = new (
  model: unknown,
  sampleRate: number,
  grammar: string,
) => RecogniserHandle

let state: VoskState = 'idle'
let recogniser: RecogniserHandle | null = null

async function init(): Promise<void> {
  if (state === 'loading' || state === 'ready') return
  state = 'loading'
  try {
    const model = await getModel()
    // Read the constructor off the package namespace; cast at this single
    // boundary — vosk-browser 0.0.8's TS types model the recogniser as a
    // nested anonymous class, but the test mock and our usage only need
    // the three methods captured by RecogniserHandle.
    const Ctor = (voskBrowser as unknown as { KaldiRecognizer: KaldiRecognizerCtor })
      .KaldiRecognizer
    recogniser = new Ctor(model, SAMPLE_RATE, JSON.stringify(VOSK_GRAMMAR))
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

  recogniser.acceptWaveform(pcm)
  const result = recogniser.finalResult()

  if (!ACCEPT_TEXTS.has(result.text)) {
    console.debug('[Vosk] rejected (text):', result.text)
    return
  }

  if (!result.result.every((w) => w.conf >= WAKE_CONF_THRESHOLD)) {
    console.debug('[Vosk] rejected (conf):', result)
    return
  }

  console.debug('[Vosk] accepted:', result.text)
  void tryDispatchCommand(result.text)
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
