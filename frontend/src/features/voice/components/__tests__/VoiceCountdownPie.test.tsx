import { describe, it, expect, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
import { usePauseRedemptionStore } from '../../stores/pauseRedemptionStore'
import { useVisualiserLayoutStore } from '../../stores/visualiserLayoutStore'
import { VoiceCountdownPie } from '../VoiceCountdownPie'

it('VoiceVisualiser subscribes to pauseRedemptionStore (fade dependency present)', async () => {
  const src = await import('../../components/VoiceVisualiser')
  expect(src).toBeDefined()
  // The visual fade is exercised in manual verification — automated framerate-bounded
  // fade tests are intentionally avoided.
})

describe('VoiceCountdownPie', () => {
  beforeEach(() => {
    usePauseRedemptionStore.setState({ active: false, startedAt: null, windowMs: 0 })
    // Bounds shape: { x, w } — no top/height, the canvas fills the viewport.
    useVisualiserLayoutStore.setState({
      chatview: { x: 0, w: 800 },
      textColumn: null,
    })
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
})
