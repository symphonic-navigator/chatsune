import { describe, it, expect, beforeEach } from 'vitest'
import { useVoiceLifecycleStore } from '../voiceLifecycleStore'

describe('voiceLifecycleStore', () => {
  beforeEach(() => {
    useVoiceLifecycleStore.getState().reset()
  })

  it('starts in active state', () => {
    expect(useVoiceLifecycleStore.getState().state).toBe('active')
  })

  it('setPause() transitions to paused', () => {
    useVoiceLifecycleStore.getState().setPause()
    expect(useVoiceLifecycleStore.getState().state).toBe('paused')
  })

  it('setActive() transitions back to active', () => {
    useVoiceLifecycleStore.getState().setPause()
    useVoiceLifecycleStore.getState().setActive()
    expect(useVoiceLifecycleStore.getState().state).toBe('active')
  })

  it('reset() returns to active from any state', () => {
    useVoiceLifecycleStore.getState().setPause()
    useVoiceLifecycleStore.getState().reset()
    expect(useVoiceLifecycleStore.getState().state).toBe('active')
  })
})
