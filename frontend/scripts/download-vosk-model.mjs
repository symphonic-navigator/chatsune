#!/usr/bin/env node
/**
 * Download the Vosk small en-US model archive into frontend/vendor/.
 *
 * vosk-browser expects `createModel(url)` to point at a single .tar.gz
 * archive — its WASM worker fetches that file, unpacks it into the
 * Emscripten in-memory FS, and caches it. We must NOT pre-extract the
 * archive on disk; vosk-browser would just throw on a directory URL.
 *
 * Source: ccoreilly.github.io is the vosk-browser maintainer's hosting
 * for pre-built tar.gz models in the format the worker expects.
 *
 * Idempotent: if vendor/vosk-model.tar.gz already exists, exits 0.
 *
 * Used both by local devs (one-time `pnpm run vosk:download` after
 * checkout) and by the Docker build (RUN before `pnpm run build`).
 */

import { mkdir } from 'node:fs/promises'
import { existsSync, createWriteStream } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { Readable } from 'node:stream'
import { pipeline } from 'node:stream/promises'

const __dirname = dirname(fileURLToPath(import.meta.url))
const FRONTEND_ROOT = resolve(__dirname, '..')
const ARCHIVE_PATH = resolve(FRONTEND_ROOT, 'vendor', 'vosk-model.tar.gz')
const MODEL_URL = 'https://ccoreilly.github.io/vosk-browser/models/vosk-model-small-en-us-0.15.tar.gz'

async function main() {
  if (existsSync(ARCHIVE_PATH)) {
    console.log('[vosk:download] archive already present, skipping')
    return
  }

  console.log('[vosk:download] downloading', MODEL_URL)
  await mkdir(dirname(ARCHIVE_PATH), { recursive: true })

  const res = await fetch(MODEL_URL)
  if (!res.ok || !res.body) {
    throw new Error(`download failed: ${res.status} ${res.statusText}`)
  }
  await pipeline(Readable.fromWeb(res.body), createWriteStream(ARCHIVE_PATH))

  console.log('[vosk:download] done — archive at', ARCHIVE_PATH)
}

main().catch((err) => {
  console.error('[vosk:download] FAILED:', err.message)
  process.exit(1)
})
