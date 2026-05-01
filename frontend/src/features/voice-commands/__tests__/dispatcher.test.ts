import { describe, it, expect, beforeEach, vi } from 'vitest'
import { tryDispatchCommand } from '../dispatcher'
import { registerCommand, _resetRegistry } from '../registry'
import type { CommandSpec, CommandResponse } from '../types'

vi.mock('../responseChannel', () => ({
  respondToUser: vi.fn(),
}))

import { respondToUser } from '../responseChannel'
const respondMock = vi.mocked(respondToUser)

function makeSpec(overrides: Partial<CommandSpec> = {}): CommandSpec {
  return {
    trigger: 'demo',
    onTriggerWhilePlaying: 'resume',
    source: 'core',
    execute: vi.fn(async (): Promise<CommandResponse> => ({
      level: 'success',
      displayText: 'ok',
    })),
    ...overrides,
  }
}

describe('tryDispatchCommand', () => {
  beforeEach(() => {
    _resetRegistry()
    respondMock.mockReset()
  })

  it('returns {dispatched:false} and does not call respondToUser when no trigger matches', async () => {
    const result = await tryDispatchCommand('hello world')
    expect(result).toEqual({ dispatched: false })
    expect(respondMock).not.toHaveBeenCalled()
  })

  it('returns {dispatched:false} for empty input', async () => {
    const result = await tryDispatchCommand('')
    expect(result).toEqual({ dispatched: false })
    expect(respondMock).not.toHaveBeenCalled()
  })

  it('returns {dispatched:false} when input is only fillers', async () => {
    const result = await tryDispatchCommand('uh um')
    expect(result).toEqual({ dispatched: false })
    expect(respondMock).not.toHaveBeenCalled()
  })

  it('executes the handler with the joined body and forwards the response', async () => {
    const spec = makeSpec()
    registerCommand(spec)
    const result = await tryDispatchCommand('demo hello world')
    expect(spec.execute).toHaveBeenCalledWith('hello world')
    expect(respondMock).toHaveBeenCalledWith({
      level: 'success',
      displayText: 'ok',
    })
    expect(result).toEqual({ dispatched: true, onTriggerWhilePlaying: 'resume' })
  })

  it('passes empty body when only the trigger word was spoken', async () => {
    const spec = makeSpec()
    registerCommand(spec)
    await tryDispatchCommand('demo')
    expect(spec.execute).toHaveBeenCalledWith('')
  })

  it('returns onTriggerWhilePlaying:abandon when the handler is configured that way', async () => {
    registerCommand(makeSpec({ onTriggerWhilePlaying: 'abandon' }))
    const result = await tryDispatchCommand('demo off')
    expect(result).toEqual({ dispatched: true, onTriggerWhilePlaying: 'abandon' })
  })

  it('catches handler throws, emits an error response, forces resume', async () => {
    const spec = makeSpec({
      onTriggerWhilePlaying: 'abandon',
      execute: vi.fn(async () => {
        throw new Error('boom')
      }),
    })
    registerCommand(spec)
    const result = await tryDispatchCommand('demo crash')
    expect(respondMock).toHaveBeenCalledWith(
      expect.objectContaining({ level: 'error' }),
    )
    expect(result).toEqual({ dispatched: true, onTriggerWhilePlaying: 'resume' })
  })

  it('strips leading fillers before matching', async () => {
    const spec = makeSpec()
    registerCommand(spec)
    await tryDispatchCommand('hey demo  do something')
    expect(spec.execute).toHaveBeenCalledWith('do something')
  })

  it('strips punctuation before matching', async () => {
    const spec = makeSpec()
    registerCommand(spec)
    await tryDispatchCommand('Demo, off.')
    expect(spec.execute).toHaveBeenCalledWith('off')
  })
})
