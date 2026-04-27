import { beforeEach, describe, expect, it } from 'vitest'
import { useVisualiserLayoutStore } from '../visualiserLayoutStore'

function reset() {
  useVisualiserLayoutStore.setState({ chatview: null, textColumn: null })
}

describe('visualiserLayoutStore', () => {
  beforeEach(reset)

  it('starts with both slots null', () => {
    const s = useVisualiserLayoutStore.getState()
    expect(s.chatview).toBeNull()
    expect(s.textColumn).toBeNull()
  })

  it('setBounds writes to the chatview slot', () => {
    useVisualiserLayoutStore.getState().setBounds('chatview', { x: 240, w: 1680 })
    expect(useVisualiserLayoutStore.getState().chatview).toEqual({ x: 240, w: 1680 })
    expect(useVisualiserLayoutStore.getState().textColumn).toBeNull()
  })

  it('setBounds writes to the textColumn slot independently', () => {
    useVisualiserLayoutStore.getState().setBounds('textColumn', { x: 816, w: 768 })
    expect(useVisualiserLayoutStore.getState().textColumn).toEqual({ x: 816, w: 768 })
    expect(useVisualiserLayoutStore.getState().chatview).toBeNull()
  })

  it('setBounds(target, null) clears the slot', () => {
    const s = useVisualiserLayoutStore.getState()
    s.setBounds('chatview', { x: 0, w: 1000 })
    s.setBounds('chatview', null)
    expect(useVisualiserLayoutStore.getState().chatview).toBeNull()
  })

  it('setting one slot does not disturb the other', () => {
    const s = useVisualiserLayoutStore.getState()
    s.setBounds('chatview', { x: 0, w: 1000 })
    s.setBounds('textColumn', { x: 116, w: 768 })
    s.setBounds('chatview', null)
    expect(useVisualiserLayoutStore.getState().chatview).toBeNull()
    expect(useVisualiserLayoutStore.getState().textColumn).toEqual({ x: 116, w: 768 })
  })
})
