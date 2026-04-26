import { beforeEach, describe, expect, it, vi } from 'vitest'

// Mock audioPlayback BEFORE the store is imported, since the store wires
// a module-init subscription on first import.
const audioPlaybackMock = {
  suspend: vi.fn(),
  unsuspend: vi.fn(),
  isActive: vi.fn(() => true),
  subscribe: vi.fn((_listener: () => void) => () => {}),
}
vi.mock('../../infrastructure/audioPlayback', () => ({
  audioPlayback: audioPlaybackMock,
}))

// Mock conversationModeStore so togglePause can read/write mic state.
const cmState = {
  active: false,
  micMuted: false,
  setMicMuted: vi.fn((value: boolean) => { cmState.micMuted = value }),
}
vi.mock('../conversationModeStore', () => ({
  useConversationModeStore: {
    getState: () => cmState,
  },
}))

let useVisualiserPauseStore: typeof import('../visualiserPauseStore').useVisualiserPauseStore
let subscribedListener: (() => void) | null = null

describe('visualiserPauseStore', () => {
  beforeEach(async () => {
    vi.resetModules()
    audioPlaybackMock.suspend.mockClear()
    audioPlaybackMock.unsuspend.mockClear()
    audioPlaybackMock.isActive.mockReset().mockReturnValue(true)
    audioPlaybackMock.subscribe.mockReset().mockImplementation((listener: () => void) => {
      subscribedListener = listener
      return () => { subscribedListener = null }
    })
    cmState.active = false
    cmState.micMuted = false
    cmState.setMicMuted.mockClear()
    subscribedListener = null
    const mod = await import('../visualiserPauseStore')
    useVisualiserPauseStore = mod.useVisualiserPauseStore
    useVisualiserPauseStore.setState({ paused: false, mutedByPause: false })
  })

  it('starts unpaused', () => {
    const s = useVisualiserPauseStore.getState()
    expect(s.paused).toBe(false)
    expect(s.mutedByPause).toBe(false)
  })

  it('togglePause in normal mode pauses TTS without touching the mic', () => {
    cmState.active = false
    useVisualiserPauseStore.getState().togglePause()
    expect(audioPlaybackMock.suspend).toHaveBeenCalledOnce()
    expect(cmState.setMicMuted).not.toHaveBeenCalled()
    expect(useVisualiserPauseStore.getState().paused).toBe(true)
    expect(useVisualiserPauseStore.getState().mutedByPause).toBe(false)
  })

  it('togglePause in Live mode with mic on mutes the mic and records the flag', () => {
    cmState.active = true
    cmState.micMuted = false
    useVisualiserPauseStore.getState().togglePause()
    expect(cmState.setMicMuted).toHaveBeenCalledWith(true)
    expect(useVisualiserPauseStore.getState().mutedByPause).toBe(true)
  })

  it('togglePause in Live mode with mic already muted does NOT record the flag', () => {
    cmState.active = true
    cmState.micMuted = true
    useVisualiserPauseStore.getState().togglePause()
    expect(cmState.setMicMuted).not.toHaveBeenCalled()
    expect(useVisualiserPauseStore.getState().mutedByPause).toBe(false)
  })

  it('togglePause when already paused resumes and unmutes if we muted', () => {
    cmState.active = true
    cmState.micMuted = false
    useVisualiserPauseStore.getState().togglePause()  // pause
    cmState.setMicMuted.mockClear()
    useVisualiserPauseStore.getState().togglePause()  // resume
    expect(audioPlaybackMock.unsuspend).toHaveBeenCalledOnce()
    expect(cmState.setMicMuted).toHaveBeenCalledWith(false)
    expect(useVisualiserPauseStore.getState().paused).toBe(false)
    expect(useVisualiserPauseStore.getState().mutedByPause).toBe(false)
  })

  it('togglePause resume does NOT unmute if we did not mute', () => {
    cmState.active = true
    cmState.micMuted = true
    useVisualiserPauseStore.getState().togglePause()  // pause; mutedByPause=false
    cmState.setMicMuted.mockClear()
    useVisualiserPauseStore.getState().togglePause()  // resume
    expect(cmState.setMicMuted).not.toHaveBeenCalled()
  })

  it('auto-clear: idle transition clears paused and restores mic if muted by us', () => {
    cmState.active = true
    cmState.micMuted = false
    useVisualiserPauseStore.getState().togglePause()
    expect(useVisualiserPauseStore.getState().paused).toBe(true)
    expect(useVisualiserPauseStore.getState().mutedByPause).toBe(true)

    audioPlaybackMock.isActive.mockReturnValue(false)
    cmState.setMicMuted.mockClear()
    subscribedListener?.()

    expect(cmState.setMicMuted).toHaveBeenCalledWith(false)
    expect(useVisualiserPauseStore.getState().paused).toBe(false)
    expect(useVisualiserPauseStore.getState().mutedByPause).toBe(false)
  })

  it('auto-clear: idle transition while NOT paused is a no-op', () => {
    audioPlaybackMock.isActive.mockReturnValue(false)
    subscribedListener?.()
    expect(cmState.setMicMuted).not.toHaveBeenCalled()
    expect(useVisualiserPauseStore.getState().paused).toBe(false)
  })

  it('auto-clear: still active → no-op', () => {
    cmState.active = true
    cmState.micMuted = false
    useVisualiserPauseStore.getState().togglePause()
    audioPlaybackMock.isActive.mockReturnValue(true)
    cmState.setMicMuted.mockClear()
    subscribedListener?.()
    expect(cmState.setMicMuted).not.toHaveBeenCalled()
    expect(useVisualiserPauseStore.getState().paused).toBe(true)
  })
})
