import { describe, expect, it, beforeEach } from 'vitest'
import { useCompanionLifecycleStore } from '../companionLifecycleStore'

describe('companionLifecycleStore', () => {
  beforeEach(() => {
    useCompanionLifecycleStore.setState({ state: 'on' })
  })

  it('defaults to ON', () => {
    expect(useCompanionLifecycleStore.getState().state).toBe('on')
  })

  it('transitions to OFF via setOff', () => {
    useCompanionLifecycleStore.getState().setOff()
    expect(useCompanionLifecycleStore.getState().state).toBe('off')
  })

  it('transitions back to ON via setOn', () => {
    useCompanionLifecycleStore.getState().setOff()
    useCompanionLifecycleStore.getState().setOn()
    expect(useCompanionLifecycleStore.getState().state).toBe('on')
  })

  it('reset returns to ON from any prior state', () => {
    useCompanionLifecycleStore.getState().setOff()
    useCompanionLifecycleStore.getState().reset()
    expect(useCompanionLifecycleStore.getState().state).toBe('on')

    useCompanionLifecycleStore.getState().setOn()
    useCompanionLifecycleStore.getState().reset()
    expect(useCompanionLifecycleStore.getState().state).toBe('on')
  })
})
