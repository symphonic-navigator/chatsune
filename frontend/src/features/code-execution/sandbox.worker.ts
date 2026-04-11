/* sandbox.worker.ts — runs user-supplied JavaScript in a Web Worker
 * with dangerous globals nulled and output captured into a bounded
 * buffer.
 *
 * The worker accepts exactly one request per instance. The host in
 * sandboxHost.ts creates a fresh worker per call and terminates it
 * after the reply — so there is no per-call cleanup to do here.
 */

interface WorkerRequest {
  code: string
  maxOutputBytes: number
}

interface WorkerResponse {
  stdout: string
  error: string | null
}

// Strip dangerous globals BEFORE anything else touches the scope.
// Each assignment is wrapped in try/catch so defineProperty-protected
// globals (should any exist) cannot crash the bootstrap.
const DANGEROUS_GLOBALS = [
  'fetch',
  'XMLHttpRequest',
  'WebSocket',
  'importScripts',
  'setTimeout',
  'setInterval',
  'clearTimeout',
  'clearInterval',
  'requestAnimationFrame',
  'cancelAnimationFrame',
  'Worker',
  'SharedWorker',
  'EventSource',
  'BroadcastChannel',
  'indexedDB',
  'caches',
] as const

for (const name of DANGEROUS_GLOBALS) {
  try {
    ;(self as unknown as Record<string, unknown>)[name] = undefined
  } catch {
    // best-effort
  }
}

function safeStringify(value: unknown): string {
  try {
    if (typeof value === 'string') return value
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

/**
 * Core execution logic — extracted so tests can call it directly
 * without a real Worker runtime.
 */
export function executeCode(code: string, maxOutputBytes: number): WorkerResponse {
  const lines: string[] = []
  let totalBytes = 0
  let truncated = false
  const encoder = new TextEncoder()

  const captureLine = (...args: unknown[]): void => {
    if (truncated) return
    const line = args.map(safeStringify).join(' ')
    const lineBytes = encoder.encode(line + '\n').length
    if (totalBytes + lineBytes > maxOutputBytes) {
      truncated = true
      const remaining = maxOutputBytes - totalBytes
      if (remaining > 0) {
        // Slice by character — inexact for multi-byte but safe. The
        // truncation marker is always appended below.
        lines.push(line.slice(0, remaining))
        totalBytes = maxOutputBytes
      }
      return
    }
    lines.push(line)
    totalBytes += lineBytes
  }

  const consoleMock = {
    log: captureLine,
    error: captureLine,
    warn: captureLine,
    info: captureLine,
    debug: captureLine,
  }

  // Bind the console mock and nulled dangerous globals into the eval scope.
  // We shadow them as local variables so indirect eval sees them even after
  // the worker's global scope has already been stripped.
  let error: string | null = null
  try {
    // We use new Function here intentionally: this module's entire purpose
    // is to execute user-supplied JavaScript in a sandboxed context. The
    // dangerous globals are shadowed via var declarations prepended to the
    // user code so they are undefined even if the runtime does not strip them.
    const nulledDeclarations = DANGEROUS_GLOBALS.map(
      (name) => `var ${name} = undefined;`,
    ).join('\n')
    const wrappedCode = `${nulledDeclarations}\nvar console = __console__;\n${code}`
    // eslint-disable-next-line no-new-func
    new Function('__console__', wrappedCode)(consoleMock)
  } catch (e) {
    error = e instanceof Error ? `${e.name}: ${e.message}` : String(e)
  }

  let stdout = lines.join('\n')
  if (truncated) {
    const marker = ' ... (output truncated)'
    const markerBytes = encoder.encode(marker).length
    // Ensure the final string, with the marker, still fits in the cap.
    if (stdout.length + markerBytes > maxOutputBytes) {
      stdout = stdout.slice(0, Math.max(0, maxOutputBytes - markerBytes))
    }
    stdout = stdout + marker
  }

  return { stdout, error }
}

self.addEventListener('message', (event: MessageEvent<WorkerRequest>) => {
  const { code, maxOutputBytes } = event.data

  const response = executeCode(code, maxOutputBytes)

  ;(self as unknown as { postMessage: (data: WorkerResponse) => void }).postMessage(
    response,
  )
})
