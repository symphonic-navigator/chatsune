import { describe, expect, it, beforeEach } from 'vitest'
import { companionCommand } from '../../handlers/companion'
import { useCompanionLifecycleStore } from '../../companionLifecycleStore'

describe('companionCommand', () => {
  beforeEach(() => {
    useCompanionLifecycleStore.setState({ state: 'on' })
  })

  it('has the static "abandon" default and trigger "companion"', () => {
    expect(companionCommand.trigger).toBe('companion')
    expect(companionCommand.onTriggerWhilePlaying).toBe('abandon')
    expect(companionCommand.source).toBe('core')
  })

  it('off while ON transitions to OFF and returns success cue:off', async () => {
    const response = await companionCommand.execute('off')
    expect(useCompanionLifecycleStore.getState().state).toBe('off')
    expect(response.level).toBe('success')
    expect(response.cue).toBe('off')
    expect(response.onTriggerWhilePlaying).toBeUndefined()  // uses static 'abandon'
  })

  it('off while already OFF is idempotent — info, no state change', async () => {
    useCompanionLifecycleStore.setState({ state: 'off' })
    const response = await companionCommand.execute('off')
    expect(useCompanionLifecycleStore.getState().state).toBe('off')
    expect(response.level).toBe('info')
    expect(response.cue).toBe('off')
  })

  it('on while OFF transitions to ON and returns success cue:on', async () => {
    useCompanionLifecycleStore.setState({ state: 'off' })
    const response = await companionCommand.execute('on')
    expect(useCompanionLifecycleStore.getState().state).toBe('on')
    expect(response.level).toBe('success')
    expect(response.cue).toBe('on')
  })

  it('on while already ON is idempotent — info, override resume', async () => {
    const response = await companionCommand.execute('on')
    expect(useCompanionLifecycleStore.getState().state).toBe('on')
    expect(response.level).toBe('info')
    expect(response.cue).toBe('on')
    expect(response.onTriggerWhilePlaying).toBe('resume')
  })

  it('status while ON returns cue:on with override resume', async () => {
    const response = await companionCommand.execute('status')
    expect(useCompanionLifecycleStore.getState().state).toBe('on')  // unchanged
    expect(response.level).toBe('info')
    expect(response.cue).toBe('on')
    expect(response.onTriggerWhilePlaying).toBe('resume')
  })

  it('status while OFF returns cue:off with override resume', async () => {
    useCompanionLifecycleStore.setState({ state: 'off' })
    const response = await companionCommand.execute('status')
    expect(useCompanionLifecycleStore.getState().state).toBe('off')  // unchanged
    expect(response.level).toBe('info')
    expect(response.cue).toBe('off')
    expect(response.onTriggerWhilePlaying).toBe('resume')
  })

  it('unknown body returns error with override resume', async () => {
    const response = await companionCommand.execute('flibbertigibbet')
    expect(response.level).toBe('error')
    expect(response.cue).toBeUndefined()
    expect(response.onTriggerWhilePlaying).toBe('resume')
  })

  it('handles empty body as unknown', async () => {
    const response = await companionCommand.execute('')
    expect(response.level).toBe('error')
  })
})
