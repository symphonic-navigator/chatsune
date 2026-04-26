import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

// Using var for TDZ-safe hoisting
var mockIsActive: ReturnType<typeof vi.fn>
var mockSubscribe: ReturnType<typeof vi.fn>
var mockTogglePause: ReturnType<typeof vi.fn>
var settingsVisualisationEnabled: boolean
var pauseStorePaused: boolean
var mqMatches: boolean

vi.mock('@/features/voice/infrastructure/audioPlayback', () => ({
  get audioPlayback() {
    return {
      isActive: mockIsActive,
      subscribe: mockSubscribe,
    }
  },
}))

vi.mock('@/features/voice/stores/voiceSettingsStore', () => ({
  useVoiceSettingsStore: <T,>(selector: (s: any) => T) =>
    selector({ visualisation: { enabled: settingsVisualisationEnabled } }),
}))

vi.mock('@/features/voice/stores/visualiserPauseStore', () => ({
  useVisualiserPauseStore: <T,>(selector: (s: any) => T) =>
    selector({ paused: pauseStorePaused, togglePause: mockTogglePause }),
}))

beforeEach(() => {
  mockIsActive = vi.fn(() => false)
  mockSubscribe = vi.fn(() => () => {})
  mockTogglePause = vi.fn()
  settingsVisualisationEnabled = true
  pauseStorePaused = false
  mqMatches = false
  vi.stubGlobal('matchMedia', (_q: string) => ({
    matches: mqMatches,
    addEventListener: (_t: string, _l: (e: { matches: boolean }) => void) => {},
    removeEventListener: () => {},
  }))
})

import { VoiceVisualiserHitStrip } from '../VoiceVisualiserHitStrip'

describe('VoiceVisualiserHitStrip', () => {
  it('renders nothing when visualiser is disabled', () => {
    settingsVisualisationEnabled = false
    mockIsActive.mockReturnValue(true)
    const { container } = render(<VoiceVisualiserHitStrip />)
    expect(container.firstChild).toBeNull()
  })

  it('renders nothing when reduced motion is set', () => {
    mqMatches = true
    mockIsActive.mockReturnValue(true)
    const { container } = render(<VoiceVisualiserHitStrip />)
    expect(container.firstChild).toBeNull()
  })

  it('renders nothing when audio is idle and not paused', () => {
    mockIsActive.mockReturnValue(false)
    pauseStorePaused = false
    const { container } = render(<VoiceVisualiserHitStrip />)
    expect(container.firstChild).toBeNull()
  })

  it('renders a button when audio is active', () => {
    mockIsActive.mockReturnValue(true)
    render(<VoiceVisualiserHitStrip />)
    expect(screen.getByRole('button')).toBeInTheDocument()
  })

  it('aria-label is "TTS pausieren" when not paused', () => {
    mockIsActive.mockReturnValue(true)
    render(<VoiceVisualiserHitStrip />)
    expect(screen.getByRole('button')).toHaveAttribute('aria-label', 'TTS pausieren')
  })

  it('aria-label is "TTS fortsetzen" when paused', () => {
    mockIsActive.mockReturnValue(true)
    pauseStorePaused = true
    render(<VoiceVisualiserHitStrip />)
    expect(screen.getByRole('button')).toHaveAttribute('aria-label', 'TTS fortsetzen')
  })

  it('still renders while paused even if isActive flips false (defensive resume path)', () => {
    mockIsActive.mockReturnValue(false)
    pauseStorePaused = true
    render(<VoiceVisualiserHitStrip />)
    expect(screen.getByRole('button')).toBeInTheDocument()
  })

  it('click invokes togglePause', () => {
    mockIsActive.mockReturnValue(true)
    render(<VoiceVisualiserHitStrip />)
    fireEvent.click(screen.getByRole('button'))
    expect(mockTogglePause).toHaveBeenCalledOnce()
  })
})
