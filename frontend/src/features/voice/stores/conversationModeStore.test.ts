import { beforeEach, describe, expect, it } from 'vitest'
import { useConversationModeStore } from './conversationModeStore'

function resetStore() {
  useConversationModeStore.setState({
    active: false,
    phase: 'idle',
    isHolding: false,
    previousReasoningOverride: null,
  })
}

describe('conversationModeStore', () => {
  beforeEach(resetStore)

  it('starts inactive in the idle phase', () => {
    const state = useConversationModeStore.getState()
    expect(state.active).toBe(false)
    expect(state.phase).toBe('idle')
    expect(state.isHolding).toBe(false)
    expect(state.previousReasoningOverride).toBeNull()
  })

  it('enter() flips active and jumps to listening', () => {
    useConversationModeStore.getState().enter()
    const state = useConversationModeStore.getState()
    expect(state.active).toBe(true)
    expect(state.phase).toBe('listening')
  })

  it('exit() resets active/phase/holding to defaults', () => {
    const s = useConversationModeStore.getState()
    s.enter()
    s.setPhase('speaking')
    s.setHolding(true)
    s.exit()
    const state = useConversationModeStore.getState()
    expect(state.active).toBe(false)
    expect(state.phase).toBe('idle')
    expect(state.isHolding).toBe(false)
  })

  it('exit() leaves the captured previous-reasoning so the controller can restore it', () => {
    const s = useConversationModeStore.getState()
    s.setPreviousReasoning(true)
    s.enter()
    s.exit()
    // previousReasoningOverride is intentionally NOT reset by exit — the
    // controller needs to read it to PATCH the server after teardown.
    expect(useConversationModeStore.getState().previousReasoningOverride).toBe(true)
  })

  it('setPhase transitions through the state machine', () => {
    const s = useConversationModeStore.getState()
    s.enter()
    const transitions: Array<import('./conversationModeStore').ConversationPhase> = [
      'user-speaking',
      'held',
      'transcribing',
      'thinking',
      'speaking',
      'listening',
    ]
    for (const p of transitions) {
      s.setPhase(p)
      expect(useConversationModeStore.getState().phase).toBe(p)
    }
  })

  it('setHolding toggles independently of phase', () => {
    const s = useConversationModeStore.getState()
    s.enter()
    s.setPhase('user-speaking')
    s.setHolding(true)
    expect(useConversationModeStore.getState().isHolding).toBe(true)
    expect(useConversationModeStore.getState().phase).toBe('user-speaking')
    s.setHolding(false)
    expect(useConversationModeStore.getState().isHolding).toBe(false)
  })

  it('setPreviousReasoning stores null | true | false distinctly', () => {
    const s = useConversationModeStore.getState()
    s.setPreviousReasoning(null)
    expect(useConversationModeStore.getState().previousReasoningOverride).toBeNull()
    s.setPreviousReasoning(true)
    expect(useConversationModeStore.getState().previousReasoningOverride).toBe(true)
    s.setPreviousReasoning(false)
    expect(useConversationModeStore.getState().previousReasoningOverride).toBe(false)
  })
})
