// Lazy, memoised registration of the SoundTouch AudioWorklet module.
// Returns a factory that builds a node connected between a source and
// destination. If module registration fails, `isAvailable` reports false
// and callers should pass audio through unmodified.

import { SoundTouchNode } from '@soundtouchjs/audio-worklet'
// Vite resolves ?url imports to a URL string at build time. The processor
// script is shipped as a separate file so the worklet can load it.
import processorUrl from '@soundtouchjs/audio-worklet/dist/soundtouch-processor.js?url'

interface LoaderState {
  initialised: boolean
  available: boolean
  error: string | null
}

const state: LoaderState = { initialised: false, available: false, error: null }
let currentContext: AudioContext | null = null

export async function ensureSoundTouchReady(ctx: AudioContext): Promise<boolean> {
  // Each AudioContext needs its own register call. If the caller gives us a
  // fresh context, re-register against it.
  if (currentContext !== ctx) {
    state.initialised = false
    currentContext = ctx
  }
  if (state.initialised) return state.available

  try {
    await SoundTouchNode.register(ctx, processorUrl)
    state.available = true
    state.error = null
  } catch (err) {
    state.available = false
    state.error = err instanceof Error ? err.message : String(err)
    console.warn('[SoundTouch] Worklet registration failed, modulation disabled:', err)
  } finally {
    state.initialised = true
  }
  return state.available
}

/**
 * Create a SoundTouchNode configured for the given speed and pitch. Returns
 * null if the worklet is not registered — caller must fall back to direct
 * routing.
 */
export function createModulationNode(
  ctx: AudioContext,
  speed: number,
  pitchSemitones: number,
): SoundTouchNode | null {
  if (!state.initialised || !state.available) return null
  const node = new SoundTouchNode(ctx)
  node.tempo.value = speed
  node.pitchSemitones.value = pitchSemitones
  return node
}
