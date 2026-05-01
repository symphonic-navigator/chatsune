/**
 * Vosk model loader — singleton.
 *
 * Loads the model from /vosk-model/ (mirrored at build time by
 * vite-plugin-static-copy from frontend/vendor/vosk-model/).
 *
 * The Model object is reused across init/dispose cycles within one
 * page-load — recogniser construction is cheap, model loading is not.
 */

import { createModel } from 'vosk-browser'

let modelPromise: Promise<unknown> | null = null

/** Lazy-loads the Vosk model. Subsequent calls return the same promise. */
export function getModel(): Promise<unknown> {
  if (!modelPromise) {
    modelPromise = createModel('/vosk-model/').catch((err) => {
      // Reset on failure so a future call can retry.
      modelPromise = null
      throw err
    })
  }
  return modelPromise
}
