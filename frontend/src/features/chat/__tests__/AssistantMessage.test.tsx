import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { act } from 'react'
import type { ReactNode } from 'react'
import { AssistantMessage } from '../AssistantMessage'
import { useIntegrationsStore } from '../../integrations/store'
import type { IntegrationDefinition } from '../../integrations/types'

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

describe('AssistantMessage — persisted tag re-render after store hydration', () => {
  const baseProps = {
    thinking: null,
    isStreaming: false,
    accentColour: '#000',
    highlighter: null,
    isBookmarked: false,
    canRegenerate: false,
  } as const

  // Reset the integrations store to a known empty state before each test.
  // This simulates the page-reload scenario where chat history loads before
  // the integrations store has populated its definitions list.
  beforeEach(() => {
    useIntegrationsStore.setState({
      definitions: [],
      configs: {},
      healthStatus: {},
      loaded: false,
      loading: false,
    })
  })

  it('re-evaluates persisted render when tag prefixes hydrate after mount', () => {
    const persistedContent = 'Before <lovense vibrate 5s> after.'
    const { rerender } = render(
      <AssistantMessage
        {...baseProps}
        content={persistedContent}
        messageId="msg-1"
      />,
    )

    // With no definitions registered, the buffer's tagPrefixes set is empty
    // and the raw `<lovense ...>` literal must survive into the rendered
    // markdown output.
    expect(screen.getByTestId('markdown').textContent).toContain(
      '<lovense vibrate 5s>',
    )

    // Now hydrate the store with a `lovense` definition that declares
    // response tag support — mirrors the late WS hello roundtrip.
    act(() => {
      const def: IntegrationDefinition = {
        id: 'lovense',
        display_name: 'Lovense',
        description: '',
        icon: '',
        execution_mode: 'frontend',
        config_fields: [],
        has_tools: false,
        has_response_tags: true,
        has_prompt_extension: false,
        capabilities: [],
        persona_config_fields: [],
      }
      useIntegrationsStore.setState({
        definitions: [def],
        loaded: true,
      })
    })

    // Force a parent rerender with identical props — the memo for the
    // persisted render now has a different tagPrefixSignature dep and must
    // rebuild. The raw tag literal must no longer appear in the rendered
    // output (it has been swapped for a placeholder, error pill or similar).
    rerender(
      <AssistantMessage
        {...baseProps}
        content={persistedContent}
        messageId="msg-1"
      />,
    )

    expect(screen.getByTestId('markdown').textContent).not.toContain(
      '<lovense vibrate 5s>',
    )
  })
})
