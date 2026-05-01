import { describe, expect, it, vi, beforeEach } from 'vitest'

vi.mock('../cuePlayer', () => ({
  playCue: vi.fn(),
}))

vi.mock('../../../core/store/notificationStore', () => ({
  useNotificationStore: {
    getState: vi.fn(() => ({
      addNotification: vi.fn(),
    })),
  },
}))

import { respondToUser } from '../responseChannel'
import { playCue } from '../cuePlayer'
import { useNotificationStore } from '../../../core/store/notificationStore'

describe('responseChannel.respondToUser', () => {
  beforeEach(() => {
    vi.mocked(playCue).mockClear()
  })

  it('plays the cue when response.cue is set', () => {
    respondToUser({ level: 'success', cue: 'on', displayText: 'on' })
    expect(playCue).toHaveBeenCalledWith('on')
    expect(playCue).toHaveBeenCalledTimes(1)
  })

  it('does not call playCue when response.cue is undefined', () => {
    respondToUser({ level: 'info', displayText: 'no cue' })
    expect(playCue).not.toHaveBeenCalled()
  })

  it('emits a toast notification regardless of cue presence', () => {
    const addNotification = vi.fn()
    vi.mocked(useNotificationStore.getState).mockReturnValue({ addNotification } as never)

    respondToUser({ level: 'success', cue: 'off', displayText: 'cue + toast' })
    expect(addNotification).toHaveBeenCalledWith({
      level: 'success',
      title: 'Voice command',
      message: 'cue + toast',
    })

    addNotification.mockClear()
    respondToUser({ level: 'info', displayText: 'toast only' })
    expect(addNotification).toHaveBeenCalledWith({
      level: 'info',
      title: 'Voice command',
      message: 'toast only',
    })
  })
})
