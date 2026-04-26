import { beforeEach, describe, expect, it, vi } from 'vitest'
import { micActivity } from '../micActivity'

describe('micActivity', () => {
  beforeEach(() => {
    micActivity.setLevel(0)
    micActivity.setVadActive(false)
  })

  it('starts at zero level and inactive VAD', () => {
    expect(micActivity.getLevel()).toBe(0)
    expect(micActivity.getVadActive()).toBe(false)
  })

  it('setLevel updates the level', () => {
    micActivity.setLevel(0.42)
    expect(micActivity.getLevel()).toBe(0.42)
  })

  it('setVadActive toggles the flag', () => {
    micActivity.setVadActive(true)
    expect(micActivity.getVadActive()).toBe(true)
    micActivity.setVadActive(false)
    expect(micActivity.getVadActive()).toBe(false)
  })

  it('subscribe fires on setLevel changes', () => {
    const listener = vi.fn()
    const unsub = micActivity.subscribe(listener)
    micActivity.setLevel(0.5)
    micActivity.setLevel(0.7)
    expect(listener).toHaveBeenCalledTimes(2)
    unsub()
  })

  it('subscribe fires on setVadActive transitions only', () => {
    const listener = vi.fn()
    const unsub = micActivity.subscribe(listener)
    micActivity.setVadActive(true)
    micActivity.setVadActive(true)   // identical → no notify
    micActivity.setVadActive(false)
    expect(listener).toHaveBeenCalledTimes(2)
    unsub()
  })

  it('unsubscribe stops further notifications', () => {
    const listener = vi.fn()
    const unsub = micActivity.subscribe(listener)
    micActivity.setLevel(0.1)
    unsub()
    micActivity.setLevel(0.2)
    expect(listener).toHaveBeenCalledTimes(1)
  })

  it('listener errors do not break the emitter loop', () => {
    const bad = vi.fn(() => { throw new Error('boom') })
    const good = vi.fn()
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    micActivity.subscribe(bad)
    micActivity.subscribe(good)
    micActivity.setLevel(0.5)
    expect(good).toHaveBeenCalledTimes(1)
    errSpy.mockRestore()
  })
})
