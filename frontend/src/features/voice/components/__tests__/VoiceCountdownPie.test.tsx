import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render } from '@testing-library/react'
import { usePauseRedemptionStore } from '../../stores/pauseRedemptionStore'
import { useVisualiserLayoutStore } from '../../stores/visualiserLayoutStore'
import { useBargeSettingsStore } from '../../stores/bargeSettingsStore'
import { VoiceCountdownPie } from '../VoiceCountdownPie'
import { usePhase } from '../../usePhase'

vi.mock('../../usePhase', () => ({
  usePhase: vi.fn(),
}))

describe('VoiceCountdownPie', () => {
  beforeEach(() => {
    usePauseRedemptionStore.setState({ active: false, startedAt: null, windowMs: 0 })
    // Bounds shape: { x, w } — no top/height, the canvas fills the viewport.
    useVisualiserLayoutStore.setState({
      chatview: { x: 0, w: 800 },
      textColumn: null,
    })
    useBargeSettingsStore.setState({ enabled: true })
    vi.mocked(usePhase).mockReturnValue('listening')
  })

  it('renders nothing when redemption is inactive', () => {
    const { container } = render(<VoiceCountdownPie personaColourHex="#d4a857" />)
    expect(container.querySelector('canvas')).toBeNull()
  })

  it('renders a canvas when redemption is active', () => {
    usePauseRedemptionStore.getState().start(1728)
    const { container } = render(<VoiceCountdownPie personaColourHex="#d4a857" />)
    const canvas = container.querySelector('canvas') as HTMLCanvasElement | null
    expect(canvas).not.toBeNull()
  })

  it('unmounts the canvas when redemption clears', () => {
    usePauseRedemptionStore.getState().start(1728)
    const { container, rerender } = render(<VoiceCountdownPie personaColourHex="#d4a857" />)
    expect(container.querySelector('canvas')).not.toBeNull()
    usePauseRedemptionStore.getState().clear()
    rerender(<VoiceCountdownPie personaColourHex="#d4a857" />)
    expect(container.querySelector('canvas')).toBeNull()
  })

  it('does not render when barging is off and the persona is speaking', () => {
    usePauseRedemptionStore.getState().start(1728)
    useBargeSettingsStore.setState({ enabled: false })
    vi.mocked(usePhase).mockReturnValue('speaking')

    const { container } = render(<VoiceCountdownPie />)
    expect(container.querySelector('canvas')).toBeNull()
  })

  it('still renders when barging is off but persona is not speaking', () => {
    usePauseRedemptionStore.getState().start(1728)
    useBargeSettingsStore.setState({ enabled: false })
    vi.mocked(usePhase).mockReturnValue('listening')

    const { container } = render(<VoiceCountdownPie />)
    expect(container.querySelector('canvas')).not.toBeNull()
  })
})
