import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import { CoverageRow } from './CoverageRow'

describe('CoverageRow', () => {
  it('renders all six capability pills', () => {
    const { container } = render(
      <CoverageRow covered={new Set(['llm'])} providersByCapability={new Map()} />,
    )
    expect(container.querySelectorAll('[data-capability]')).toHaveLength(6)
  })

  it('marks covered pills with data-covered=true', () => {
    const { container } = render(
      <CoverageRow covered={new Set(['llm', 'tts'])} providersByCapability={new Map()} />,
    )
    expect(container.querySelectorAll('[data-covered="true"]')).toHaveLength(2)
  })
})
