// NOTE: Neither jsdom nor happy-dom provide a real Worker runtime in Vitest.
// We therefore use the direct-import fallback: executeCode is exported from
// sandbox.worker.ts and called here directly. This preserves full behavioural
// coverage — the eval, console capture, truncation, and global-stripping logic
// are all exercised. The only thing not covered is the postMessage round-trip,
// which is trivial glue tested by later integration tasks.
import { describe, expect, it } from 'vitest'
import { executeCode } from '../sandbox.worker'

async function runCode(code: string, maxOutputBytes = 4096) {
  return executeCode(code, maxOutputBytes)
}

describe('sandbox.worker', () => {
  it('runs simple arithmetic via console.log', async () => {
    const r = await runCode('console.log(2 + 2)')
    expect(r.error).toBeNull()
    expect(r.stdout.trim()).toBe('4')
  })

  it('counts characters in erdbeere', async () => {
    const r = await runCode("console.log([...'erdbeere'].filter(c => c === 'r').length)")
    expect(r.error).toBeNull()
    expect(r.stdout.trim()).toBe('2')
  })

  it('reports exceptions as error strings', async () => {
    const r = await runCode('throw new Error("boom")')
    expect(r.stdout).toBe('')
    expect(r.error).toContain('Error: boom')
  })

  it('blocks fetch by nulling the global', async () => {
    const r = await runCode('fetch("https://evil.example")')
    expect(r.stdout).toBe('')
    expect(r.error).toContain('TypeError')
  })

  it('truncates output beyond the max budget', async () => {
    const r = await runCode(
      'for (let i = 0; i < 10000; i++) console.log("xxxxxxxxxx")',
      256,
    )
    const byteLength = new TextEncoder().encode(r.stdout).length
    expect(byteLength).toBeLessThanOrEqual(256)
    expect(r.stdout).toContain('(output truncated)')
  })

  it('returns the BigInt result for 2^53 + 1', async () => {
    const r = await runCode('console.log((2n ** 53n + 1n).toString())')
    expect(r.error).toBeNull()
    expect(r.stdout.trim()).toBe('9007199254740993')
  })
})
