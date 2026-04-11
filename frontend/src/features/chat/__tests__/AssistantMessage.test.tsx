import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { AssistantMessage } from '../AssistantMessage'

describe('AssistantMessage — refusal', () => {
  const baseProps = {
    thinking: null,
    isStreaming: false,
    accentColour: '#000',
    highlighter: null,
    isBookmarked: false,
    onBookmark: () => {},
    canRegenerate: false,
    onRegenerate: () => {},
  } as const

  it('renders content and red band when refused with content', () => {
    render(
      <AssistantMessage
        {...baseProps}
        content="Sorry, I will not help with that"
        status="refused"
        refusalText={null}
      />
    )
    expect(screen.getByText(/Sorry, I will not help with that/)).toBeInTheDocument()
    expect(screen.getByText(/The model declined this request/)).toBeInTheDocument()
  })

  it('renders refusalText when content is empty', () => {
    render(
      <AssistantMessage
        {...baseProps}
        content=""
        status="refused"
        refusalText="Model declined"
      />
    )
    expect(screen.getByText(/Model declined/)).toBeInTheDocument()
  })

  it('renders fallback when both content and refusalText are empty', () => {
    render(
      <AssistantMessage
        {...baseProps}
        content=""
        status="refused"
        refusalText={null}
      />
    )
    expect(screen.getAllByText(/The model declined this request/).length).toBeGreaterThan(0)
  })

  it('ignores refusalText when status is completed', () => {
    render(
      <AssistantMessage
        {...baseProps}
        content="Hello"
        status="completed"
        refusalText="Stray refusal"
      />
    )
    expect(screen.getByText('Hello')).toBeInTheDocument()
    expect(screen.queryByText('Stray refusal')).not.toBeInTheDocument()
  })

  it('still renders amber band when status is aborted (regression)', () => {
    render(
      <AssistantMessage
        {...baseProps}
        content="partial"
        status="aborted"
        refusalText={null}
      />
    )
    expect(screen.getByText(/interrupted/i)).toBeInTheDocument()
  })
})
