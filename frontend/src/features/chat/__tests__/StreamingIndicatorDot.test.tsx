import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { useChatStore } from '../../../core/store/chatStore'
import { StreamingIndicatorDot } from '../StreamingIndicatorDot'

describe('StreamingIndicatorDot', () => {
  beforeEach(() => {
    useChatStore.setState({ streamsBySession: new Map() })
  })

  it('renders nothing when no stream exists for the session', () => {
    const { container } = render(<StreamingIndicatorDot sessionId="x" />)
    expect(container.firstChild).toBeNull()
  })

  it('renders the dot when a stream is active for the session', () => {
    useChatStore.getState().startStreaming('cor-1', { sessionId: 'x' })
    render(<StreamingIndicatorDot sessionId="x" />)
    expect(screen.getByLabelText('response streaming')).toBeInTheDocument()
  })

  it('does not render for a different session id', () => {
    useChatStore.getState().startStreaming('cor-1', { sessionId: 'x' })
    const { container } = render(<StreamingIndicatorDot sessionId="y" />)
    expect(container.firstChild).toBeNull()
  })
})
