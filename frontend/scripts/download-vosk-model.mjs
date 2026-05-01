#!/usr/bin/env node
/**
 * Download and unpack the Vosk small en-US model into frontend/vendor/vosk-model.
 *
 * Idempotent: if vendor/vosk-model/am/final.mdl already exists, exits 0.
 * Otherwise fetches from alphacephei.com, unzips, flattens the top-level
 * versioned directory.
 *
 * Used both by local devs (one-time `pnpm run vosk:download` after checkout)
 * and by the Docker build (RUN before `pnpm run build`).
 *
 * If alphacephei.com becomes unreachable, mirror the .zip somewhere we
 * control and update MODEL_URL.
 */

import { mkdir, rm, readdir, rename } from 'node:fs/promises'
import { existsSync, createWriteStream } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'
import { Readable } from 'node:stream'
import { pipeline } from 'node:stream/promises'

const __dirname = dirname(fileURLToPath(import.meta.url))
const FRONTEND_ROOT = resolve(__dirname, '..')
const VENDOR_DIR = resolve(FRONTEND_ROOT, 'vendor', 'vosk-model')
const PROBE_FILE = resolve(VENDOR_DIR, 'am', 'final.mdl')
const MODEL_URL = 'https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip'
const ZIP_PATH = resolve(VENDOR_DIR, '..', 'vosk-model.zip')
const TMP_EXTRACT = resolve(VENDOR_DIR, '..', 'vosk-extract-tmp')

async function main() {
  if (existsSync(PROBE_FILE)) {
    console.log('[vosk:download] model already present, skipping')
    return
  }

  console.log('[vosk:download] downloading', MODEL_URL)
  await mkdir(dirname(ZIP_PATH), { recursive: true })

  // Always re-downloads (overwrites any truncated zip from a previous interrupt).
  const res = await fetch(MODEL_URL)
  if (!res.ok || !res.body) {
    throw new Error(`download failed: ${res.status} ${res.statusText}`)
  }
  await pipeline(Readable.fromWeb(res.body), createWriteStream(ZIP_PATH))

  console.log('[vosk:download] unzipping')
  await rm(VENDOR_DIR, { recursive: true, force: true })
  await mkdir(VENDOR_DIR, { recursive: true })
  await rm(TMP_EXTRACT, { recursive: true, force: true })
  await mkdir(TMP_EXTRACT, { recursive: true })

  try {
    // Use system unzip — adding a Node-native zip dependency would bloat the
    // dev install. The zip extracts into vosk-model-small-en-us-0.15/, which
    // we flatten by moving its contents up one level using Node-native
    // readdir + rename (no POSIX-shell dependency, works on Windows too).
    const unzipResult = spawnSync('unzip', ['-q', ZIP_PATH, '-d', TMP_EXTRACT], { stdio: 'inherit' })
    if (unzipResult.status !== 0) {
      throw new Error('unzip failed — install `unzip` (e.g. `apt install unzip`)')
    }

    const inner = resolve(TMP_EXTRACT, 'vosk-model-small-en-us-0.15')
    const entries = await readdir(inner)
    await Promise.all(entries.map((name) =>
      rename(resolve(inner, name), resolve(VENDOR_DIR, name)),
    ))
  } finally {
    // Clean up the tmp directory and zip even if unzip/rename throws —
    // prevents stale artefacts on local-dev failures. (In Docker the
    // failed RUN layer is discarded anyway, so this only matters locally.)
    await rm(TMP_EXTRACT, { recursive: true, force: true })
    await rm(ZIP_PATH, { force: true })
  }

  if (!existsSync(PROBE_FILE)) {
    throw new Error(`model layout unexpected: ${PROBE_FILE} missing after extract`)
  }

  console.log('[vosk:download] done — model at', VENDOR_DIR)
}

main().catch((err) => {
  console.error('[vosk:download] FAILED:', err.message)
  process.exit(1)
})
