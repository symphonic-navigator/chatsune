import { describe, it, expect } from 'vitest'
import { derivePhase, type DerivePhaseInput } from '../derivePhase'

function inp(overrides: Partial<DerivePhaseInput> = {}): DerivePhaseInput {
  return {
    active: true,
    isHolding: false,
    vadActive: false,
    bargeState: null,
    sttInFlight: false,
    groupState: null,
    ...overrides,
  }
}

describe('derivePhase', () => {
  describe('rule 1: active=false wins over everything', () => {
    it('returns idle when inactive even if all other inputs are set', () => {
      expect(derivePhase(inp({
        active: false,
        isHolding: true,
        vadActive: true,
        bargeState: 'pending-stt',
        sttInFlight: true,
        groupState: 'streaming',
      }))).toBe('idle')
    })

    it('returns idle on the bare inactive input', () => {
      expect(derivePhase(inp({ active: false }))).toBe('idle')
    })
  })

  describe('rule 2: isHolding wins over barge / vad / group', () => {
    it('returns held when isHolding, regardless of other reactive inputs', () => {
      expect(derivePhase(inp({
        isHolding: true,
        vadActive: true,
        bargeState: 'pending-stt',
        sttInFlight: true,
        groupState: 'streaming',
      }))).toBe('held')
    })

    it('returns held on the bare isHolding input', () => {
      expect(derivePhase(inp({ isHolding: true }))).toBe('held')
    })
  })

  describe('rule 3: pending-stt maps to transcribing or user-speaking', () => {
    it('pending-stt + sttInFlight=false → user-speaking', () => {
      expect(derivePhase(inp({ bargeState: 'pending-stt', sttInFlight: false })))
        .toBe('user-speaking')
    })

    it('pending-stt + sttInFlight=true → transcribing', () => {
      expect(derivePhase(inp({ bargeState: 'pending-stt', sttInFlight: true })))
        .toBe('transcribing')
    })

    it('pending-stt wins over vadActive', () => {
      expect(derivePhase(inp({
        bargeState: 'pending-stt',
        sttInFlight: true,
        vadActive: true,
      }))).toBe('transcribing')
    })

    it('pending-stt wins over groupState', () => {
      expect(derivePhase(inp({
        bargeState: 'pending-stt',
        sttInFlight: false,
        groupState: 'streaming',
      }))).toBe('user-speaking')
    })
  })

  describe('rule 4: vadActive maps to user-speaking when no committed barge', () => {
    it('vadActive=true with bargeState=null → user-speaking', () => {
      expect(derivePhase(inp({ vadActive: true }))).toBe('user-speaking')
    })

    it('vadActive wins over groupState', () => {
      expect(derivePhase(inp({ vadActive: true, groupState: 'streaming' })))
        .toBe('user-speaking')
    })
  })

  describe('rule 5: fall through by groupState', () => {
    it('before-first-delta → thinking', () => {
      expect(derivePhase(inp({ groupState: 'before-first-delta' })))
        .toBe('thinking')
    })

    it('streaming → speaking', () => {
      expect(derivePhase(inp({ groupState: 'streaming' }))).toBe('speaking')
    })

    it('tailing → speaking', () => {
      expect(derivePhase(inp({ groupState: 'tailing' }))).toBe('speaking')
    })

    it('done → listening', () => {
      expect(derivePhase(inp({ groupState: 'done' }))).toBe('listening')
    })

    it('cancelled → listening', () => {
      expect(derivePhase(inp({ groupState: 'cancelled' }))).toBe('listening')
    })

    it('null groupState → listening', () => {
      expect(derivePhase(inp({ groupState: null }))).toBe('listening')
    })
  })

  describe('non-pending barge states fall through deterministically', () => {
    it('confirmed + groupState=streaming → speaking', () => {
      expect(derivePhase(inp({ bargeState: 'confirmed', groupState: 'streaming' })))
        .toBe('speaking')
    })

    it('resumed + groupState=tailing → speaking', () => {
      expect(derivePhase(inp({ bargeState: 'resumed', groupState: 'tailing' })))
        .toBe('speaking')
    })

    it('stale + groupState=null → listening', () => {
      expect(derivePhase(inp({ bargeState: 'stale', groupState: null })))
        .toBe('listening')
    })

    it('abandoned + groupState=done → listening', () => {
      expect(derivePhase(inp({ bargeState: 'abandoned', groupState: 'done' })))
        .toBe('listening')
    })
  })
})
