/**
 * Vosk model loader — singleton.
 *
 * vosk-browser's createModel(url) wants a SINGLE .tar.gz archive URL —
 * its WASM worker fetches the archive and unpacks it inside Emscripten's
 * in-memory FS. Do not point at a pre-extracted directory; the worker
 * will throw or hang.
 *
 * The archive is mirrored at /vosk-model.tar.gz at build time by
 * vite-plugin-static-copy from frontend/vendor/vosk-model.tar.gz.
 *
 * The Model object is reused across init/dispose cycles within one
 * page-load — recogniser construction is cheap, model loading is not.
 */

import { createModel } from 'vosk-browser'

const MODEL_URL = '/vosk-model.tar.gz'

let modelPromise: Promise<unknown> | null = null

/** Lazy-loads the Vosk model. Subsequent calls return the same promise. */
export function getModel(): Promise<unknown> {
  if (!modelPromise) {
    console.info('[Vosk] loading model from', MODEL_URL)
    const startedAt = performance.now()
    modelPromise = createModel(MODEL_URL)
      .then((model) => {
        console.info('[Vosk] model loaded in %d ms', Math.round(performance.now() - startedAt))
        return model
      })
      .catch((err) => {
        console.error('[Vosk] model load FAILED — is the model served at', MODEL_URL, '?', err)
        // Reset on failure so a future call can retry.
        modelPromise = null
        throw err
      })
  }
  return modelPromise
}
