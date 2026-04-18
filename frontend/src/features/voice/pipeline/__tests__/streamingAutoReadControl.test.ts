import { beforeEach, describe, expect, it, vi } from 'vitest'

describe('streamingAutoReadControl', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('returns null when no session is active', async () => {
    const mod = await import('../streamingAutoReadControl')
    expect(mod.getActiveStreamingAutoRead()).toBeNull()
  })

  it('set/get round-trips a session', async () => {
    const mod = await import('../streamingAutoReadControl')
    const fake = {
      messageId: 'm1',
      cancelled: false,
    } as unknown as import('../streamingAutoReadControl').StreamingAutoReadSession
    mod.setActiveStreamingAutoRead(fake)
    expect(mod.getActiveStreamingAutoRead()).toBe(fake)
    mod.setActiveStreamingAutoRead(null)
    expect(mod.getActiveStreamingAutoRead()).toBeNull()
  })

  it('cancelStreamingAutoRead flips the cancelled flag and clears the slot', async () => {
    const mod = await import('../streamingAutoReadControl')
    const fake = {
      messageId: 'm1',
      cancelled: false,
    } as unknown as import('../streamingAutoReadControl').StreamingAutoReadSession
    mod.setActiveStreamingAutoRead(fake)
    mod.cancelStreamingAutoRead()
    expect(fake.cancelled).toBe(true)
    expect(mod.getActiveStreamingAutoRead()).toBeNull()
  })

  it('cancelStreamingAutoRead is idempotent when no session is active', async () => {
    const mod = await import('../streamingAutoReadControl')
    // Should not throw — it just no-ops.
    expect(() => mod.cancelStreamingAutoRead()).not.toThrow()
    expect(mod.getActiveStreamingAutoRead()).toBeNull()
  })
})
