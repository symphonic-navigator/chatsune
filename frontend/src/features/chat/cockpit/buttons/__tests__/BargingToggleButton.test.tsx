import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { BargingToggleButton } from '../BargingToggleButton'
import { useBargeSettingsStore } from '@/features/voice/stores/bargeSettingsStore'

// Mock usePhase so each test can pin the phase deterministically.
vi.mock('@/features/voice/usePhase', () => ({
  usePhase: vi.fn(),
}))
import { usePhase } from '@/features/voice/usePhase'

describe('BargingToggleButton', () => {
  beforeEach(() => {
    useBargeSettingsStore.setState({ enabled: true })
    window.localStorage.clear()
    vi.mocked(usePhase).mockReturnValue('listening')
  })

  it('renders the open-lips glyph in green when enabled (any phase)', () => {
    useBargeSettingsStore.setState({ enabled: true })
    vi.mocked(usePhase).mockReturnValue('speaking')
    render(<BargingToggleButton />)
    const btn = screen.getByRole('button')
    expect(btn).toHaveAttribute('data-barge-state', 'on')
    expect(btn.className).toMatch(/text-\[#4ade80\]|text-green/)
    expect(btn.querySelector('[data-glyph="lips-open"]')).not.toBeNull()
  })

  it('renders the lips-with-slash glyph in red, no pulse, when disabled and not speaking', () => {
    useBargeSettingsStore.setState({ enabled: false })
    vi.mocked(usePhase).mockReturnValue('listening')
    render(<BargingToggleButton />)
    const btn = screen.getByRole('button')
    expect(btn).toHaveAttribute('data-barge-state', 'off-idle')
    expect(btn.className).toMatch(/text-\[#ef4444\]|text-red/)
    expect(btn.className).not.toMatch(/animate-pulse-slow/)
    expect(btn.querySelector('[data-glyph="lips-slash"]')).not.toBeNull()
  })

  it('renders the mic-with-slash glyph pulsing when disabled and speaking', () => {
    useBargeSettingsStore.setState({ enabled: false })
    vi.mocked(usePhase).mockReturnValue('speaking')
    render(<BargingToggleButton />)
    const btn = screen.getByRole('button')
    expect(btn).toHaveAttribute('data-barge-state', 'off-speaking')
    expect(btn.className).toMatch(/text-\[#ef4444\]|text-red/)
    expect(btn.className).toMatch(/animate-pulse-slow/)
    expect(btn.querySelector('[data-glyph="mic-slash"]')).not.toBeNull()
  })

  it('toggles the store on click', () => {
    useBargeSettingsStore.setState({ enabled: true })
    render(<BargingToggleButton />)
    expect(screen.getByRole('button')).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(screen.getByRole('button'))
    expect(useBargeSettingsStore.getState().enabled).toBe(false)
    expect(screen.getByRole('button')).toHaveAttribute('aria-pressed', 'false')
    fireEvent.click(screen.getByRole('button'))
    expect(useBargeSettingsStore.getState().enabled).toBe(true)
    expect(screen.getByRole('button')).toHaveAttribute('aria-pressed', 'true')
  })

  it('uses tooltip text matching the active state', () => {
    useBargeSettingsStore.setState({ enabled: true })
    const { rerender } = render(<BargingToggleButton />)
    expect(screen.getByRole('button').title).toMatch(/can interrupt/i)

    useBargeSettingsStore.setState({ enabled: false })
    vi.mocked(usePhase).mockReturnValue('listening')
    rerender(<BargingToggleButton />)
    expect(screen.getByRole('button').title).toMatch(/can't be interrupted|tap to enable/i)

    vi.mocked(usePhase).mockReturnValue('speaking')
    rerender(<BargingToggleButton />)
    expect(screen.getByRole('button').title).toMatch(/asleep|while persona speaks/i)
  })
})
