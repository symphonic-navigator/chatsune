import type { DtypeEntry } from '../infrastructure/dtypeLadder'

export type AttemptOutcome = 'ok' | 'load-failed' | 'warmup-failed' | 'gpu-error'

export interface Attempt {
  entry: DtypeEntry
  outcome: AttemptOutcome
  detail?: string
}

export interface WalkOk<T> {
  ok: true
  entry: DtypeEntry
  model: T
  attempts: Attempt[]
}

export interface WalkFailed {
  ok: false
  attempts: Attempt[]
}

export type WalkResult<T> = WalkOk<T> | WalkFailed

export interface WalkOptions<T> {
  ladder: readonly DtypeEntry[]
  /** Load the model for this entry. May throw on load failure. */
  load: (entry: DtypeEntry) => Promise<T>
  /** Run a quick warmup against the loaded model. May throw on failure. */
  warmup: (entry: DtypeEntry, model: T) => Promise<void>
  /** Return any WebGPU uncaptured errors that occurred during load+warmup. */
  collectGpuErrors: (entry: DtypeEntry) => Promise<string[]>
  /** Optional logger for per-step trace output. */
  log?: (line: string) => void
}

function formatEntry(e: DtypeEntry): string {
  return `${e.device}/${e.dtype}`
}

export async function walkLadder<T>(opts: WalkOptions<T>): Promise<WalkResult<T>> {
  const { ladder, load, warmup, collectGpuErrors, log } = opts
  const attempts: Attempt[] = []

  for (const entry of ladder) {
    log?.(`try ${formatEntry(entry)}`)
    let model: T
    try {
      model = await load(entry)
    } catch (err) {
      attempts.push({ entry, outcome: 'load-failed', detail: String(err) })
      log?.(`  ${formatEntry(entry)} — LOAD FAILED: ${String(err)}`)
      continue
    }

    try {
      await warmup(entry, model)
    } catch (err) {
      attempts.push({ entry, outcome: 'warmup-failed', detail: String(err) })
      log?.(`  ${formatEntry(entry)} — WARMUP FAILED: ${String(err)}`)
      continue
    }

    const gpuErrors = await collectGpuErrors(entry)
    if (gpuErrors.length > 0) {
      attempts.push({ entry, outcome: 'gpu-error', detail: gpuErrors.join('; ') })
      log?.(`  ${formatEntry(entry)} — GPU ERROR: ${gpuErrors.join('; ')}`)
      continue
    }

    attempts.push({ entry, outcome: 'ok' })
    log?.(`  ${formatEntry(entry)} — OK`)
    return { ok: true, entry, model, attempts }
  }

  return { ok: false, attempts }
}
