import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ThinkingBubble } from '../ThinkingBubble'

describe('ThinkingBubble', () => {
  it('renders thinking content', () => {
    render(<ThinkingBubble content="Let me reason about this" isStreaming={false} accentColour="#7c5cbf" />)
    expect(screen.getByText(/Let me reason/)).toBeInTheDocument()
  })

  it('is expanded while streaming', () => {
    render(<ThinkingBubble content="thinking..." isStreaming={true} accentColour="#7c5cbf" />)
    expect(screen.getByText(/thinking\.\.\./)).toBeVisible()
  })

  it('auto-collapses when streaming ends', () => {
    const { rerender } = render(<ThinkingBubble content="thinking" isStreaming={true} accentColour="#7c5cbf" />)
    rerender(<ThinkingBubble content="done thinking" isStreaming={false} accentColour="#7c5cbf" />)
    const contentDiv = screen.getByTestId('thinking-content')
    expect(contentDiv.style.maxHeight).toBe('0px')
  })

  it('shows pulsing dots only while streaming', () => {
    const { rerender } = render(<ThinkingBubble content="" isStreaming={true} accentColour="#7c5cbf" />)
    expect(screen.getByTestId('thinking-dots')).toBeInTheDocument()
    rerender(<ThinkingBubble content="done" isStreaming={false} accentColour="#7c5cbf" />)
    expect(screen.queryByTestId('thinking-dots')).not.toBeInTheDocument()
  })
})
