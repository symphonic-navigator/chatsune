import { beforeEach, describe, expect, it } from 'vitest'
import { useConversationModeStore } from './conversationModeStore'

function resetStore() {
  useConversationModeStore.setState({
    active: false,
    isHolding: false,
    previousReasoningOverride: null,
    currentBargeState: null,
    sttInFlight: false,
    vadActive: false,
  })
}

describe('conversationModeStore', () => {
  beforeEach(resetStore)

  it('starts inactive with all reactive-source flags at their defaults', () => {
    const state = useConversationModeStore.getState()
    expect(state.active).toBe(false)
    expect(state.isHolding).toBe(false)
    expect(state.previousReasoningOverride).toBeNull()
    expect(state.currentBargeState).toBeNull()
    expect(state.sttInFlight).toBe(false)
    expect(state.vadActive).toBe(false)
  })

  it('enter() flips active on', () => {
    useConversationModeStore.getState().enter()
    expect(useConversationModeStore.getState().active).toBe(true)
  })

  it('exit() resets active/holding to defaults', () => {
    const s = useConversationModeStore.getState()
    s.enter()
    s.setHolding(true)
    s.exit()
    const state = useConversationModeStore.getState()
    expect(state.active).toBe(false)
    expect(state.isHolding).toBe(false)
  })

  it('exit() resets currentBargeState/sttInFlight/vadActive to defaults', () => {
    const s = useConversationModeStore.getState()
    s.enter()
    s.setCurrentBargeState('pending-stt')
    s.setSttInFlight(true)
    s.setVadActive(true)
    s.exit()
    const state = useConversationModeStore.getState()
    expect(state.currentBargeState).toBeNull()
    expect(state.sttInFlight).toBe(false)
    expect(state.vadActive).toBe(false)
  })

  it('setCurrentBargeState / setSttInFlight / setVadActive update their fields', () => {
    const s = useConversationModeStore.getState()
    s.setCurrentBargeState('confirmed')
    expect(useConversationModeStore.getState().currentBargeState).toBe('confirmed')
    s.setCurrentBargeState(null)
    expect(useConversationModeStore.getState().currentBargeState).toBeNull()

    s.setSttInFlight(true)
    expect(useConversationModeStore.getState().sttInFlight).toBe(true)
    s.setSttInFlight(false)
    expect(useConversationModeStore.getState().sttInFlight).toBe(false)

    s.setVadActive(true)
    expect(useConversationModeStore.getState().vadActive).toBe(true)
    s.setVadActive(false)
    expect(useConversationModeStore.getState().vadActive).toBe(false)
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

  it('setHolding toggles independently of other state', () => {
    const s = useConversationModeStore.getState()
    s.enter()
    s.setHolding(true)
    expect(useConversationModeStore.getState().isHolding).toBe(true)
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
