import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { tryDispatchCommand } from '../dispatcher'
import { registerCommand, _resetRegistry } from '../registry'
import { voiceCommand } from '../handlers/voice'
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

  it('uses response.onTriggerWhilePlaying override when handler returns one', async () => {
    registerCommand({
      trigger: 'override',
      onTriggerWhilePlaying: 'abandon',  // static default
      source: 'core',
      execute: async () => ({
        level: 'info',
        displayText: 'overridden',
        onTriggerWhilePlaying: 'resume',  // per-response override
      }),
    })

    const result = await tryDispatchCommand('override')

    expect(result).toEqual({ dispatched: true, onTriggerWhilePlaying: 'resume' })
  })

  it('falls back to spec default when response has no onTriggerWhilePlaying', async () => {
    registerCommand({
      trigger: 'nooverride',
      onTriggerWhilePlaying: 'abandon',
      source: 'core',
      execute: async () => ({
        level: 'info',
        displayText: 'static',
      }),
    })

    const result = await tryDispatchCommand('nooverride')

    expect(result).toEqual({ dispatched: true, onTriggerWhilePlaying: 'abandon' })
  })
})

describe('voice-trigger gate', () => {
  let warnSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    _resetRegistry()
    respondMock.mockReset()
    registerCommand(voiceCommand)
    warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  afterEach(() => {
    warnSpy.mockRestore()
  })

  describe('strict-reject (2-token unknown sub)', () => {
    it('rejects "voice nope" without dispatching to LLM', async () => {
      const r = await tryDispatchCommand('voice nope')
      expect(r.dispatched).toBe(true)
      if (r.dispatched) expect(r.onTriggerWhilePlaying).toBe('resume')
      expect(warnSpy).toHaveBeenCalledWith(
        expect.stringContaining('Rejected 2-token'),
        expect.anything(),
      )
    })

    it('strips trailing punctuation before reject check ("voice nope.")', async () => {
      const r = await tryDispatchCommand('voice nope.')
      expect(r.dispatched).toBe(true)
      expect(warnSpy).toHaveBeenCalled()
    })
  })

  describe('fall-through (1 token or 3+ tokens, unknown sub)', () => {
    it('falls through for single-token "voice"', async () => {
      const r = await tryDispatchCommand('voice')
      expect(r.dispatched).toBe(false)
      expect(warnSpy).not.toHaveBeenCalled()
    })

    it('falls through for 3-token "voice that is great"', async () => {
      const r = await tryDispatchCommand('voice that is great')
      expect(r.dispatched).toBe(false)
      expect(warnSpy).not.toHaveBeenCalled()
    })

    it('falls through for 4-token "voice mode is great"', async () => {
      const r = await tryDispatchCommand('voice mode is great')
      expect(r.dispatched).toBe(false)
      expect(warnSpy).not.toHaveBeenCalled()
    })
  })

  describe('known sub at any token count proceeds normally', () => {
    it('"voice off" (2 tokens, known) → dispatches', async () => {
      const r = await tryDispatchCommand('voice off')
      expect(r.dispatched).toBe(true)
      expect(warnSpy).not.toHaveBeenCalled()
    })

    it('"voice off please now" (4 tokens, known sub) → dispatches', async () => {
      const r = await tryDispatchCommand('voice off please now')
      expect(r.dispatched).toBe(true)
      expect(warnSpy).not.toHaveBeenCalled()
    })
  })
})
