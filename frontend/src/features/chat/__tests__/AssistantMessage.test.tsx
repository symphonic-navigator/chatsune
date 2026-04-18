import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { AssistantMessage } from '../AssistantMessage'

// Shared render counter for the mocked ReactMarkdown. Exposed as a global so
// the memoisation tests can assert on how often AssistantMessage actually
// re-entered its render body.
const markdownRenderSpy = vi.fn()

vi.mock('react-markdown', () => ({
  default: ({ children }: { children?: ReactNode }) => {
    markdownRenderSpy()
    return <div data-testid="markdown">{children}</div>
  },
}))

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

describe('AssistantMessage — memoisation', () => {
  const baseProps = {
    thinking: null,
    isStreaming: false,
    accentColour: '#000',
    highlighter: null,
    isBookmarked: false,
    canRegenerate: false,
  } as const

  it('re-renders when content changes', () => {
    const onBookmark = vi.fn()
    markdownRenderSpy.mockClear()
    const { rerender } = render(
      <AssistantMessage {...baseProps} content="first" onBookmark={onBookmark} />
    )
    const before = markdownRenderSpy.mock.calls.length
    rerender(<AssistantMessage {...baseProps} content="second" onBookmark={onBookmark} />)
    expect(markdownRenderSpy.mock.calls.length).toBeGreaterThan(before)
  })

  it('does NOT re-render when only the onBookmark callback identity changes', () => {
    markdownRenderSpy.mockClear()
    const { rerender } = render(
      <AssistantMessage {...baseProps} content="stable content" onBookmark={vi.fn()} />
    )
    const before = markdownRenderSpy.mock.calls.length
    rerender(
      <AssistantMessage {...baseProps} content="stable content" onBookmark={vi.fn()} />
    )
    // With memo + equality that ignores function props, AssistantMessage must be
    // skipped entirely, so the markdown child is not re-rendered.
    expect(markdownRenderSpy.mock.calls.length).toBe(before)
  })
})
