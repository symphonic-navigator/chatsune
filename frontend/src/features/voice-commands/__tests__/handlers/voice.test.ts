import { describe, it, expect, beforeEach } from 'vitest'
import { voiceCommand } from '../../handlers/voice'
import { useVoiceLifecycleStore } from '../../voiceLifecycleStore'

const PAUSE_TOAST = 'Paused — say "voice on" to resume.'
const ACTIVE_TOAST = 'Listening — say "voice off" to pause.'

describe('voiceCommand', () => {
  beforeEach(() => {
    useVoiceLifecycleStore.getState().reset()
  })

  describe('pause synonyms', () => {
    for (const sub of ['pause', 'off', 'of'] as const) {
      it(`'${sub}' transitions to paused, plays off cue, abandons`, async () => {
        const r = await voiceCommand.execute(sub)
        expect(r.level).toBe('success')
        expect(r.cue).toBe('off')
        expect(r.displayText).toBe(PAUSE_TOAST)
        expect(r.onTriggerWhilePlaying).toBeUndefined()
        expect(useVoiceLifecycleStore.getState().state).toBe('paused')
      })
    }
  })

  describe('active synonyms', () => {
    for (const sub of ['continue', 'on', 'resume'] as const) {
      it(`'${sub}' from paused transitions to active`, async () => {
        useVoiceLifecycleStore.getState().setPause()
        const r = await voiceCommand.execute(sub)
        expect(r.level).toBe('success')
        expect(r.cue).toBe('on')
        expect(r.displayText).toBe(ACTIVE_TOAST)
        expect(useVoiceLifecycleStore.getState().state).toBe('active')
      })
    }

    it('idempotent already-active path returns resume override', async () => {
      const r = await voiceCommand.execute('on')
      expect(r.level).toBe('info')
      expect(r.onTriggerWhilePlaying).toBe('resume')
      expect(useVoiceLifecycleStore.getState().state).toBe('active')
    })
  })

  describe('status synonyms', () => {
    for (const sub of ['status', 'state'] as const) {
      it(`'${sub}' while active returns active toast and on cue`, async () => {
        const r = await voiceCommand.execute(sub)
        expect(r.cue).toBe('on')
        expect(r.displayText).toBe(ACTIVE_TOAST)
        expect(r.onTriggerWhilePlaying).toBe('resume')
        expect(useVoiceLifecycleStore.getState().state).toBe('active')
      })

      it(`'${sub}' while paused returns paused toast and off cue`, async () => {
        useVoiceLifecycleStore.getState().setPause()
        const r = await voiceCommand.execute(sub)
        expect(r.cue).toBe('off')
        expect(r.displayText).toBe(PAUSE_TOAST)
        expect(r.onTriggerWhilePlaying).toBe('resume')
        expect(useVoiceLifecycleStore.getState().state).toBe('paused')
      })
    }
  })

  describe('unknown sub', () => {
    it('returns error and does not transition', async () => {
      const r = await voiceCommand.execute('nope')
      expect(r.level).toBe('error')
      expect(r.onTriggerWhilePlaying).toBe('resume')
      expect(useVoiceLifecycleStore.getState().state).toBe('active')
    })
  })

  describe('static spec metadata', () => {
    it('has the trigger "voice"', () => {
      expect(voiceCommand.trigger).toBe('voice')
    })
    it('defaults onTriggerWhilePlaying to abandon', () => {
      expect(voiceCommand.onTriggerWhilePlaying).toBe('abandon')
    })
    it('source is core', () => {
      expect(voiceCommand.source).toBe('core')
    })
  })
})
