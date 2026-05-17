import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MessageList } from '../../MessageList'
import type { ChatMessageDto, TimelineEntry } from '../../../../core/api/chat'

// Replicate the lightweight chatStore mock used by MessageList.test.tsx —
// MessageList reads ``messagePillContents`` / ``compactionCheckpoints`` /
// ``activeSessionId`` from the store but never exercises any setters here.
vi.mock('../../../../core/store/chatStore', () => {
  const state = {
    messagePillContents: {},
    activeSessionId: null,
    compactionCheckpoints: [] as unknown[],
  }
  const useChatStore = ((selector: (s: typeof state) => unknown) =>
    selector(state)) as unknown as {
    (selector: (s: typeof state) => unknown): unknown
    getState: () => typeof state
  }
  useChatStore.getState = () => state
  return { useChatStore }
})

// ArtefactCard is the only timeline-entry pill that pulls heavy renderers
// transitively; stub it to keep the test light.
vi.mock('../../../artefact/ArtefactCard', () => ({
  ArtefactCard: () => <div data-testid="artefact-card" />,
}))

function makeMsg(overrides: Partial<ChatMessageDto>): ChatMessageDto {
  return {
    id: 'm1',
    session_id: 's1',
    role: 'assistant',
    content: 'hello',
    thinking: null,
    token_count: 0,
    attachments: null,
    web_search_context: null,
    knowledge_context: null,
    created_at: new Date().toISOString(),
    ...overrides,
  } as ChatMessageDto
}

const noop = () => {}
const noopRef = { current: null } as React.RefObject<HTMLDivElement | null>

const baseProps = {
  sessionId: 's1',
  streamingContent: '',
  streamingThinking: '',
  streamingEvents: [] as TimelineEntry[],
  streamingToolCalls: new Map(),
  isWaitingForResponse: false,
  isStreaming: false,
  visionDescriptions: {},
  streamingCorrelationId: null,
  streamingSlow: false,
  accentColour: '#000',
  highlighter: null,
  containerRef: noop,
  bottomRef: noopRef,
  showScrollButton: false,
  onScrollToBottom: noop,
  onEdit: noop,
  onRegenerate: noop,
  bookmarkedMessageIds: new Set<string>(),
  onBookmark: noop,
}

describe('MessageList — assistant action bar (branching)', () => {
  it('last assistant shows [Regenerate] + [Branch]', () => {
    const messages = [
      makeMsg({ id: 'u1', role: 'user', content: 'hi' }),
      makeMsg({ id: 'a1', role: 'assistant', content: 'hello' }),
    ]
    render(<MessageList {...baseProps} messages={messages} onBranch={vi.fn()} />)
    const regen = screen.getByTestId('assistant-regenerate')
    expect(regen.textContent).toContain('Regenerate')
    expect(regen.textContent).not.toContain('Branch & Regenerate')
    expect(screen.getByTestId('assistant-branch')).toBeInTheDocument()
  })

  it('non-last assistant shows [Branch & Regenerate] + [Branch]', () => {
    const messages = [
      makeMsg({ id: 'u1', role: 'user', content: 'hi' }),
      makeMsg({ id: 'a1', role: 'assistant', content: 'first reply' }),
      makeMsg({ id: 'u2', role: 'user', content: 'follow-up' }),
      makeMsg({ id: 'a2', role: 'assistant', content: 'second reply' }),
    ]
    render(<MessageList {...baseProps} messages={messages} onBranch={vi.fn()} />)
    // Both assistants render an action bar, but only the FIRST assistant's
    // regenerate button is re-labelled — the second is the last one.
    const regens = screen.getAllByTestId('assistant-regenerate')
    // Order in the DOM matches message order, so [0] is the earlier
    // (non-last) assistant and [1] is the last.
    expect(regens[0].textContent).toContain('Branch & Regenerate')
    expect(regens[1].textContent).toContain('Regenerate')
    expect(regens[1].textContent).not.toContain('Branch & Regenerate')
    // Both messages get a Branch button (spec §6.1).
    expect(screen.getAllByTestId('assistant-branch')).toHaveLength(2)
  })

  it('onBranch is called with the assistant message id when [Branch] is clicked', () => {
    const onBranch = vi.fn()
    const messages = [
      makeMsg({ id: 'u1', role: 'user', content: 'hi' }),
      makeMsg({ id: 'a1', role: 'assistant', content: 'hello' }),
    ]
    render(<MessageList {...baseProps} messages={messages} onBranch={onBranch} />)
    screen.getByTestId('assistant-branch').click()
    expect(onBranch).toHaveBeenCalledWith('a1')
  })

  it('onRegenerate carries messageId and isLastAssistant when invoked', () => {
    const onRegenerate = vi.fn()
    const messages = [
      makeMsg({ id: 'u1', role: 'user', content: 'hi' }),
      makeMsg({ id: 'a1', role: 'assistant', content: 'first' }),
      makeMsg({ id: 'u2', role: 'user', content: 'follow-up' }),
      makeMsg({ id: 'a2', role: 'assistant', content: 'second' }),
    ]
    render(
      <MessageList
        {...baseProps}
        messages={messages}
        onRegenerate={onRegenerate}
        onBranch={vi.fn()}
      />,
    )
    const regens = screen.getAllByTestId('assistant-regenerate')
    // First (non-last) regenerate → triggers branch-and-regenerate path.
    regens[0].click()
    expect(onRegenerate).toHaveBeenCalledWith({
      messageId: 'a1',
      isLastAssistant: false,
    })
    regens[1].click()
    expect(onRegenerate).toHaveBeenCalledWith({
      messageId: 'a2',
      isLastAssistant: true,
    })
  })

  it('without onBranch, only the last assistant shows the regenerate button', () => {
    const messages = [
      makeMsg({ id: 'u1', role: 'user', content: 'hi' }),
      makeMsg({ id: 'a1', role: 'assistant', content: 'first' }),
      makeMsg({ id: 'u2', role: 'user', content: 'follow-up' }),
      makeMsg({ id: 'a2', role: 'assistant', content: 'second' }),
    ]
    // No onBranch → legacy behaviour (incognito). Only the last assistant
    // gets a Regenerate button; non-last assistants render no action.
    render(<MessageList {...baseProps} messages={messages} />)
    const regens = screen.queryAllByTestId('assistant-regenerate')
    expect(regens).toHaveLength(1)
    expect(regens[0].textContent).toContain('Regenerate')
    expect(screen.queryAllByTestId('assistant-branch')).toHaveLength(0)
  })

  it('renders the "Aus Parent geklont" subtitle on cloned timeline entries', () => {
    const messages = [
      makeMsg({
        id: 'a1',
        role: 'assistant',
        events: [
          {
            kind: 'tool_call',
            seq: 0,
            tool_call_id: 'tc1',
            tool_name: 'web_search',
            arguments: {},
            success: true,
            result_content: 'cached result',
            cloned_from_branch: true,
          },
        ],
      }),
    ]
    render(<MessageList {...baseProps} messages={messages} />)
    expect(screen.getByTestId('cloned-from-branch-subtitle')).toBeInTheDocument()
    expect(
      screen.getByText('Aus Parent geklont — nicht erneut ausgeführt'),
    ).toBeInTheDocument()
  })

  it('does not render the subtitle when cloned_from_branch is missing/false', () => {
    const messages = [
      makeMsg({
        id: 'a1',
        role: 'assistant',
        events: [
          {
            kind: 'tool_call',
            seq: 0,
            tool_call_id: 'tc1',
            tool_name: 'web_search',
            arguments: {},
            success: true,
            result_content: 'fresh result',
          },
        ],
      }),
    ]
    render(<MessageList {...baseProps} messages={messages} />)
    expect(
      screen.queryByTestId('cloned-from-branch-subtitle'),
    ).not.toBeInTheDocument()
  })
})
