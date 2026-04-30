import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MessageList, mergePtiIntoFirstKnowledgeEntry } from '../MessageList'
import type { ChatMessageDto, TimelineEntry } from '../../../core/api/chat'

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
// AssistantMessage additionally reads messagePillContents to look up cached
// inline-trigger pills for the rendered message id.
vi.mock('../../../core/store/chatStore', () => ({
  useChatStore: (selector: (s: { visionDescriptions: Record<string, unknown>; correlationId: null; streamingSlow: boolean; messagePillContents: Record<string, Map<string, string>> }) => unknown) =>
    selector({ visionDescriptions: {}, correlationId: null, streamingSlow: false, messagePillContents: {} }),
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

describe('MessageList — persisted timeline rendering', () => {
  const baseProps = {
    sessionId: 's1',
    streamingContent: '',
    streamingThinking: '',
    streamingEvents: [] as TimelineEntry[],
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
  }

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders ArtefactCard for an artefact timeline entry', () => {
    const messages = [
      makeMsg({
        events: [
          {
            kind: 'artefact',
            seq: 0,
            ref: {
              artefact_id: 'a1', handle: 'h1', title: 't1',
              artefact_type: 'code', operation: 'create',
            },
          },
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
        events: [
          {
            kind: 'artefact',
            seq: 0,
            ref: {
              artefact_id: '', handle: 'h2', title: 't2',
              artefact_type: 'code', operation: 'update',
            },
          },
        ],
      }),
    ]
    render(<MessageList {...baseProps} messages={messages} />)
    const card = screen.getByTestId('artefact-card')
    expect(card.textContent).toContain('h2/t2/update')
  })

  it('renders multiple artefact entries in seq order', () => {
    const messages = [
      makeMsg({
        events: [
          {
            kind: 'artefact',
            seq: 0,
            ref: {
              artefact_id: 'a1', handle: 'h', title: 't1',
              artefact_type: 'code', operation: 'create',
            },
          },
          {
            kind: 'artefact',
            seq: 1,
            ref: {
              artefact_id: '', handle: 'h', title: 't2',
              artefact_type: 'code', operation: 'update',
            },
          },
        ],
      }),
    ]
    render(<MessageList {...baseProps} messages={messages} />)
    const cards = screen.getAllByTestId('artefact-card')
    expect(cards).toHaveLength(2)
    expect(cards[0].textContent).toContain('t1')
    expect(cards[1].textContent).toContain('t2')
  })

  it('renders nothing when events is null', () => {
    const messages = [makeMsg({ events: null })]
    render(<MessageList {...baseProps} messages={messages} />)
    expect(screen.queryByTestId('artefact-card')).not.toBeInTheDocument()
  })

  it('renders timeline entries in DOM order matching the events list', () => {
    // [knowledge_search@0, web_search@1, artefact@2] should appear in
    // exactly that visual order. We assert by document position of each
    // representative element.
    const messages = [
      makeMsg({
        events: [
          {
            kind: 'knowledge_search',
            seq: 0,
            items: [
              {
                library_name: 'lib', document_title: 'KnowledgeDoc',
                content: 'c', source: 'search',
              },
            ],
          },
          {
            kind: 'web_search',
            seq: 1,
            items: [{ title: 'WebHit', url: 'https://x', snippet: 's' }],
          },
          {
            kind: 'artefact',
            seq: 2,
            ref: {
              artefact_id: 'a1', handle: 'h1', title: 'ArtefactTitle',
              artefact_type: 'code', operation: 'create',
            },
          },
        ],
      }),
    ]
    const { container } = render(<MessageList {...baseProps} messages={messages} />)
    const html = container.innerHTML
    const knowledgeIdx = html.indexOf('KnowledgeDoc')
    const webIdx = html.indexOf('WebHit')
    const artefactIdx = html.indexOf('ArtefactTitle')
    expect(knowledgeIdx).toBeGreaterThan(-1)
    expect(webIdx).toBeGreaterThan(-1)
    expect(artefactIdx).toBeGreaterThan(-1)
    expect(knowledgeIdx).toBeLessThan(webIdx)
    expect(webIdx).toBeLessThan(artefactIdx)
  })
})

describe('mergePtiIntoFirstKnowledgeEntry', () => {
  it('prepends PTI items into the first knowledge_search entry', () => {
    const events: TimelineEntry[] = [
      {
        kind: 'knowledge_search',
        seq: 0,
        items: [
          {
            library_name: 'lib', document_title: 'assistant-doc',
            content: 'a', source: 'search',
          },
        ],
      },
    ]
    const pti = [
      {
        library_name: 'lib', document_title: 'pti-doc',
        content: 'p', source: 'trigger' as const,
      },
    ]
    const merged = mergePtiIntoFirstKnowledgeEntry(events, pti, null)
    expect(merged).toHaveLength(1)
    const e = merged[0]
    expect(e.kind).toBe('knowledge_search')
    if (e.kind === 'knowledge_search') {
      expect(e.items.map((i) => i.document_title)).toEqual(['pti-doc', 'assistant-doc'])
      expect(e.seq).toBe(0)
    }
  })

  it('inserts a synthetic knowledge_search entry when none exists', () => {
    const events: TimelineEntry[] = [
      {
        kind: 'web_search',
        seq: 0,
        items: [{ title: 't', url: 'u', snippet: 's' }],
      },
    ]
    const pti = [
      {
        library_name: 'lib', document_title: 'pti-doc',
        content: 'p', source: 'trigger' as const,
      },
    ]
    const overflow = { dropped_count: 1, dropped_titles: ['x'] }
    const merged = mergePtiIntoFirstKnowledgeEntry(events, pti, overflow)
    expect(merged).toHaveLength(2)
    const first = merged[0]
    expect(first.kind).toBe('knowledge_search')
    if (first.kind === 'knowledge_search') {
      expect(first.seq).toBe(-1)
      expect(first.items).toEqual(pti)
      expect(first._overflow).toEqual(overflow)
    }
    expect(merged[1].kind).toBe('web_search')
  })

  it('returns events unchanged when there is no PTI and no overflow', () => {
    const events: TimelineEntry[] = [
      {
        kind: 'web_search',
        seq: 0,
        items: [{ title: 't', url: 'u', snippet: 's' }],
      },
    ]
    const merged = mergePtiIntoFirstKnowledgeEntry(events, [], null)
    expect(merged).toBe(events)
  })

  it('attaches _overflow to the existing knowledge_search entry when PTI items are empty', () => {
    const events: TimelineEntry[] = [
      {
        kind: 'knowledge_search',
        seq: 0,
        items: [
          {
            library_name: 'lib', document_title: 'assistant-doc',
            content: 'a', source: 'search',
          },
        ],
      },
    ]
    const overflow = { dropped_count: 2, dropped_titles: ['a', 'b'] }
    const merged = mergePtiIntoFirstKnowledgeEntry(events, [], overflow)
    const e = merged[0]
    expect(e.kind).toBe('knowledge_search')
    if (e.kind === 'knowledge_search') {
      expect(e._overflow).toEqual(overflow)
      expect(e.items.map((i) => i.document_title)).toEqual(['assistant-doc'])
    }
  })
})
