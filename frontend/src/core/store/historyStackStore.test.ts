import { beforeEach, describe, expect, it } from 'vitest'
import { useHistoryStackStore } from './historyStackStore'

beforeEach(() => {
  useHistoryStackStore.getState().clear()
})

describe('historyStackStore', () => {
  it('starts with an empty stack', () => {
    expect(useHistoryStackStore.getState().stack).toEqual([])
    expect(useHistoryStackStore.getState().peek()).toBeNull()
  })

  it('push adds to the top', () => {
    const onClose = () => {}
    useHistoryStackStore.getState().push('user-modal', onClose)
    expect(useHistoryStackStore.getState().stack).toHaveLength(1)
    expect(useHistoryStackStore.getState().peek()?.overlayId).toBe('user-modal')
  })

  it('preserves stack order across multiple pushes', () => {
    const noop = () => {}
    useHistoryStackStore.getState().push('a', noop)
    useHistoryStackStore.getState().push('b', noop)
    useHistoryStackStore.getState().push('c', noop)
    expect(useHistoryStackStore.getState().stack.map((e) => e.overlayId)).toEqual(['a', 'b', 'c'])
    expect(useHistoryStackStore.getState().peek()?.overlayId).toBe('c')
  })

  it('popTop removes and returns the top entry', () => {
    const noop = () => {}
    useHistoryStackStore.getState().push('a', noop)
    useHistoryStackStore.getState().push('b', noop)
    const popped = useHistoryStackStore.getState().popTop()
    expect(popped?.overlayId).toBe('b')
    expect(useHistoryStackStore.getState().stack.map((e) => e.overlayId)).toEqual(['a'])
  })

  it('popTop returns null on empty stack', () => {
    expect(useHistoryStackStore.getState().popTop()).toBeNull()
  })

  it('duplicate push of same overlayId replaces, does not duplicate', () => {
    const first = () => {}
    const second = () => {}
    useHistoryStackStore.getState().push('user-modal', first)
    useHistoryStackStore.getState().push('user-modal', second)
    expect(useHistoryStackStore.getState().stack).toHaveLength(1)
    expect(useHistoryStackStore.getState().peek()?.onClose).toBe(second)
  })

  it('clear empties the stack', () => {
    const noop = () => {}
    useHistoryStackStore.getState().push('a', noop)
    useHistoryStackStore.getState().push('b', noop)
    useHistoryStackStore.getState().clear()
    expect(useHistoryStackStore.getState().stack).toEqual([])
  })
})
