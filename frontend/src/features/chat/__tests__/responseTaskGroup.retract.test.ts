import { describe, it, expect, vi } from 'vitest'
import { createResponseTaskGroup } from '../responseTaskGroup'

describe('ResponseTaskGroup retract path', () => {
  it('cancel from before-first-delta sends exactly chat.retract', () => {
    const sendWs = vi.fn()
    const logger = { info: vi.fn(), debug: vi.fn(), warn: vi.fn(), error: vi.fn() }
    const g = createResponseTaskGroup({
      correlationId: 'c1', sessionId: 's1', userId: 'u1',
      children: [], sendWsMessage: sendWs, logger,
    })
    g.cancel('barge-retract')
    expect(sendWs).toHaveBeenCalledTimes(1)
    expect(sendWs).toHaveBeenCalledWith({
      type: 'chat.retract', correlation_id: 'c1',
    })
  })

  it('after first delta, cancel sends chat.cancel', () => {
    const sendWs = vi.fn()
    const logger = { info: vi.fn(), debug: vi.fn(), warn: vi.fn(), error: vi.fn() }
    const g = createResponseTaskGroup({
      correlationId: 'c1', sessionId: 's1', userId: 'u1',
      children: [], sendWsMessage: sendWs, logger,
    })
    g.onDelta('a')
    g.cancel('barge-cancel')
    expect(sendWs).toHaveBeenCalledTimes(1)
    expect(sendWs).toHaveBeenCalledWith({
      type: 'chat.cancel', correlation_id: 'c1',
    })
  })
})
