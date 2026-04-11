import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MessageList } from '../MessageList'
import type { ChatMessageDto } from '../../../core/api/chat'

// Mock ArtefactCard to a simple identifying div so tests only verify
// rendering contract, not the card's internals.
vi.mock('../../artefact/ArtefactCard', () => ({
  ArtefactCard: ({ handle, title, isUpdate }: { handle: string; title: string; artefactType: string; isUpdate: boolean; sessionId: string }) => (
    <div data-testid="artefact-card">
      {handle}/{title}/{isUpdate ? 'update' : 'create'}
    </div>
  ),
}))

// Mock chatStore — MessageList reads visionDescriptions, correlationId, streamingSlow
vi.mock('../../../core/store/chatStore', () => ({
  useChatStore: (selector: (s: { visionDescriptions: Record<string, unknown>; correlationId: null; streamingSlow: boolean }) => unknown) =>
    selector({ visionDescriptions: {}, correlationId: null, streamingSlow: false }),
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

describe('MessageList — persisted artefact rendering', () => {
  const baseProps = {
    sessionId: 's1',
    streamingContent: '',
    streamingThinking: '',
    streamingWebSearchContext: [],
    streamingKnowledgeContext: [],
    activeToolCalls: [],
    isWaitingForResponse: false,
    isStreaming: false,
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
  } as const

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders ArtefactCard for each persisted artefact_ref', () => {
    const messages = [
      makeMsg({
        artefact_refs: [
          { artefact_id: 'a1', handle: 'h1', title: 't1',
            artefact_type: 'code', operation: 'create' },
        ],
      }),
    ]
    render(<MessageList {...baseProps} messages={messages} />)
    const card = screen.getByTestId('artefact-card')
    expect(card.textContent).toContain('h1/t1/create')
  })

  it('renders update operation cards distinctly', () => {
    const messages = [
      makeMsg({
        artefact_refs: [
          { artefact_id: '', handle: 'h2', title: 't2',
            artefact_type: 'code', operation: 'update' },
        ],
      }),
    ]
    render(<MessageList {...baseProps} messages={messages} />)
    const card = screen.getByTestId('artefact-card')
    expect(card.textContent).toContain('h2/t2/update')
  })

  it('renders multiple artefact_refs in order', () => {
    const messages = [
      makeMsg({
        artefact_refs: [
          { artefact_id: 'a1', handle: 'h', title: 't1',
            artefact_type: 'code', operation: 'create' },
          { artefact_id: '', handle: 'h', title: 't2',
            artefact_type: 'code', operation: 'update' },
        ],
      }),
    ]
    render(<MessageList {...baseProps} messages={messages} />)
    const cards = screen.getAllByTestId('artefact-card')
    expect(cards).toHaveLength(2)
    expect(cards[0].textContent).toContain('t1')
    expect(cards[1].textContent).toContain('t2')
  })

  it('renders no ArtefactCard when artefact_refs is missing', () => {
    const messages = [makeMsg({ artefact_refs: null })]
    render(<MessageList {...baseProps} messages={messages} />)
    expect(screen.queryByTestId('artefact-card')).not.toBeInTheDocument()
  })
})
