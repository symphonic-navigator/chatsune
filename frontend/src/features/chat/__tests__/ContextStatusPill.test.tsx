import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ContextStatusPill } from '../ContextStatusPill'

describe('ContextStatusPill', () => {
  it('shows green with no label', () => {
    render(<ContextStatusPill status="green" fillPercentage={0.3} />)
    const dot = screen.getByTestId('context-dot')
    expect(dot.className).toContain('bg-green-500')
  })

  it('shows yellow with percentage', () => {
    render(<ContextStatusPill status="yellow" fillPercentage={0.55} />)
    expect(screen.getByText('55%')).toBeInTheDocument()
  })

  it('shows orange with percentage', () => {
    render(<ContextStatusPill status="orange" fillPercentage={0.72} />)
    expect(screen.getByText('72%')).toBeInTheDocument()
  })

  it('shows red with percentage', () => {
    render(<ContextStatusPill status="red" fillPercentage={0.85} />)
    expect(screen.getByText('85%')).toBeInTheDocument()
  })
})
