/* sandboxHost.ts — main-thread wrapper around sandbox.worker.ts.
 *
 * Creates a fresh Worker per call and terminates it after the reply.
 * No pooling: Worker creation overhead is tiny compared to the tool
 * round-trip, and a new Worker gives the strongest possible form of
 * state isolation.
 */

export interface SandboxResult {
  stdout: string
  error: string | null
}

export async function runSandbox(
  code: string,
  timeoutMs: number,
  maxOutputBytes: number,
): Promise<SandboxResult> {
  const worker = new Worker(
    new URL('./sandbox.worker.ts', import.meta.url),
    { type: 'module' },
  )

  const result = await new Promise<SandboxResult>((resolve) => {
    let settled = false
    const settle = (value: SandboxResult): void => {
      if (settled) return
      settled = true
      resolve(value)
    }

    const timeoutHandle = setTimeout(() => {
      worker.terminate()
      settle({
        stdout: '',
        error: `Client-side timeout after ${timeoutMs}ms`,
      })
    }, timeoutMs)

    worker.addEventListener('message', (event: MessageEvent<SandboxResult>) => {
      clearTimeout(timeoutHandle)
      settle(event.data)
    })

    worker.addEventListener('error', (event: ErrorEvent) => {
      clearTimeout(timeoutHandle)
      settle({
        stdout: '',
        error: `Sandbox crash: ${event.message || 'unknown error'}`,
      })
    })

    worker.postMessage({ code, maxOutputBytes })
  })

  // Unconditional terminate covers the happy path (terminate() on an
  // already-terminated Worker is a safe no-op).
  worker.terminate()
  return result
}
