// Mindspace — Task 6: Persona-loaded race in neutral-trigger session create.
//
// When the user clicks a neutral trigger (sidebar persona pin, persona
// overlay "New chat", User-overlay → Personas → row → "New chat"), the
// flow lands on ``/chat/{personaId}?new=1``. ChatView's resolve effect
// must wait until ``persona`` has loaded before calling
// ``chatApi.createSession`` — otherwise the session is created with
// ``project_id=null`` because ``persona?.default_project_id`` is
// ``undefined`` while the personas fetch is still in flight.

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import type { PersonaDto } from '../../../core/types/persona'

// ---------------------------------------------------------------------------
// chatApi — the actual subject of the assertion. Other api modules are
// mocked to no-ops so the resolve effect can run without hitting network.

// chatApi mock — the explicit ``createSession`` spy is the assertion
// target; everything else falls through to a Proxy-backed no-op so we
// don't have to enumerate every method ChatView happens to touch.
vi.mock('../../../core/api/chat', () => {
  const explicit: Record<string, ReturnType<typeof vi.fn>> = {
    createSession: vi.fn().mockResolvedValue({
      id: 's1',
      persona_id: 'p1',
      project_id: 'proj-1',
      title: null,
      pinned: false,
      tools_enabled: false,
      auto_read: false,
      reasoning_override: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }),
    listSessions: vi.fn().mockResolvedValue([]),
    listToolGroups: vi.fn().mockResolvedValue([]),
    listMessages: vi.fn().mockResolvedValue([]),
    listSessionAttachments: vi.fn().mockResolvedValue([]),
    listProjects: vi.fn().mockResolvedValue([]),
    getMessages: vi.fn().mockResolvedValue({ messages: [], events: [] }),
    getSession: vi.fn().mockResolvedValue({
      id: 's1',
      persona_id: 'p1',
      project_id: 'proj-1',
      title: null,
      pinned: false,
      tools_enabled: false,
      auto_read: false,
      reasoning_override: null,
    }),
  }
  return {
    chatApi: new Proxy(explicit, {
      get(target, prop: string) {
        if (prop in target) return target[prop]
        // Default: a fire-and-forget async no-op, sufficient for any
        // method ChatView calls during mount that we don't assert on.
        const stub = vi.fn().mockResolvedValue(undefined)
        target[prop] = stub
        return stub
      },
    }),
  }
})

vi.mock('../../../core/api/bookmarks', () => ({
  bookmarksApi: {
    list: vi.fn().mockResolvedValue([]),
    create: vi.fn(),
    delete: vi.fn(),
  },
}))

vi.mock('../../artefact/artefactApi', () => ({
  artefactApi: { listForSession: vi.fn().mockResolvedValue([]) },
}))

vi.mock('../../../core/api/artefact', () => ({
  artefactApi: {
    list: vi.fn().mockResolvedValue([]),
    listForSession: vi.fn().mockResolvedValue([]),
  },
}))

// ---------------------------------------------------------------------------
// Heavy stores / hooks — return inert defaults. The resolve effect under
// test does not depend on any of these; we just need the component to
// render past the early hooks without throwing.

vi.mock('../../../core/store/chatStore', () => {
  const state = {
    messages: [],
    isWaitingForResponse: false,
    isStreaming: false,
    streamingContent: '',
    streamingThinking: '',
    streamingEvents: [],
    activeToolCalls: [],
    contextStatus: null,
    contextFillPercentage: null,
    contextUsedTokens: null,
    contextMaxTokens: null,
    error: null,
    sessionTitle: null,
    visionDescriptions: {},
    correlationId: null,
    streamingSlow: false,
    messagePillContents: {},
    reset: vi.fn(),
  }
  const useChatStore = ((selector?: (s: typeof state) => unknown) =>
    selector ? selector(state) : state) as unknown as {
    (selector: (s: typeof state) => unknown): unknown
    getState: () => typeof state
  }
  useChatStore.getState = () => state
  return { useChatStore }
})

vi.mock('../../../core/store/artefactStore', () => {
  const state = {
    reset: vi.fn(),
    sidebarOpen: false,
    artefacts: [],
    toggleSidebar: vi.fn(),
    activeArtefact: null,
    overlayArtefactId: null,
  }
  const useArtefactStore = ((selector?: (s: typeof state) => unknown) =>
    selector ? selector(state) : state) as unknown as {
    (selector: (s: typeof state) => unknown): unknown
    getState: () => typeof state
  }
  useArtefactStore.getState = () => state
  return { useArtefactStore }
})

vi.mock('../../../core/store/memoryStore', () => {
  // ``uncommittedEntries`` is keyed by personaId; unknown personas
  // must return an empty array so ChatView's ``.length`` access is safe.
  const uncommittedEntries = new Proxy(
    {},
    { get: () => [] as never[] },
  ) as Record<string, never[]>
  return {
    useMemoryStore: (selector?: (s: object) => unknown) =>
      selector ? selector({ uncommittedEntries }) : {},
  }
})

vi.mock('../../../core/store/notificationStore', () => ({
  useNotificationStore: (selector?: (s: object) => unknown) => (selector ? selector({}) : {}),
}))

vi.mock('../../../core/hooks/useEnrichedModels', () => ({
  useEnrichedModels: () => ({
    findByUniqueId: () => null,
    groups: [],
    loading: false,
  }),
}))

vi.mock('../../../core/hooks/useBookmarks', () => ({
  useBookmarks: () => ({ bookmarks: [], setBookmarks: () => {} }),
}))

vi.mock('../../../core/hooks/useViewport', () => ({
  useViewport: () => ({ isMobile: false, isTablet: false, isDesktop: true }),
}))

vi.mock('../../../core/hooks/useWakeLock', () => ({
  useWakeLock: () => {},
}))

vi.mock('../../../core/websocket/connection', () => ({
  sendMessage: vi.fn(),
}))

vi.mock('../../../core/websocket/eventBus', () => ({
  eventBus: {
    on: () => () => {},
    off: () => {},
    emit: () => {},
    subscribe: () => () => {},
  },
}))

vi.mock('../useChatStream', () => ({ useChatStream: () => {} }))
vi.mock('../useAutoScroll', () => ({
  useAutoScroll: () => ({
    containerRef: () => {},
    bottomRef: { current: null },
    showScrollButton: false,
    scrollToBottom: () => {},
  }),
}))
vi.mock('../useMarkdown', () => ({ useHighlighter: () => null }))
vi.mock('../useAttachments', () => ({
  useAttachments: () => ({
    attachments: [],
    add: () => {},
    remove: () => {},
    clear: () => {},
  }),
}))

vi.mock('../cockpit/cockpitStore', () => ({
  useCockpitStore: (selector?: (s: object) => unknown) => (selector ? selector({}) : {}),
}))

vi.mock('../../mcp/mcpStore', () => ({
  useMcpStore: (selector?: (s: object) => unknown) =>
    selector
      ? selector({
          servers: [],
          excludedGateways: new Set(),
          sessionGateways: [],
        })
      : {},
}))

vi.mock('../../integrations/store', () => ({
  useIntegrationsStore: (selector?: (s: object) => unknown) =>
    selector ? selector({ definitions: [], configs: [] }) : {},
}))

vi.mock('../../memory/useMemoryEvents', () => ({ useMemoryEvents: () => {} }))

vi.mock('../../artefact/useArtefactEvents', () => ({ useArtefactEvents: () => {} }))

vi.mock('../../voice/stores/voiceSettingsStore', () => ({
  useVoiceSettingsStore: (selector?: (s: object) => unknown) =>
    selector
      ? selector({
          autoSendTranscription: false,
          voiceActivationThreshold: 0.5,
        })
      : {},
}))

vi.mock('../../voice/engines/resolver', () => ({
  resolveSTTEngine: () => null,
  resolveTTSEngine: () => null,
  resolveTTSIntegrationId: () => null,
}))

vi.mock('../../voice/engines/defaults', () => ({ resolveGapMs: () => 0 }))

vi.mock('../../voice/engines/expressiveMarkupCapability', () => ({
  providerSupportsExpressiveMarkup: () => false,
}))

vi.mock('../../voice/stores/voicePipelineStore', () => ({
  useVoicePipeline: (selector?: (s: object) => unknown) =>
    selector ? selector({ state: 'idle', setState: () => {} }) : {},
}))

vi.mock('../../voice/hooks/useCtrlSpace', () => ({ useCtrlSpace: () => {} }))

vi.mock('../../voice/pipeline/voicePipeline', () => ({
  // Proxy returns a no-op for any method ChatView happens to call.
  voicePipeline: new Proxy(
    {},
    { get: () => () => undefined },
  ),
}))

vi.mock('../../voice/pipeline/applyModulation', () => ({ resolveModulation: () => null }))

vi.mock('../../voice/stores/conversationModeStore', () => ({
  useConversationModeStore: (selector?: (s: object) => unknown) =>
    selector ? selector({ mode: 'idle' }) : {},
}))

vi.mock('../../voice/hooks/useConversationMode', () => ({ useConversationMode: () => {} }))

vi.mock('../../voice/usePhase', () => ({ usePhase: () => 'idle' }))

vi.mock('../responseTaskGroup', () => ({
  createResponseTaskGroup: () => ({}),
  registerActiveGroup: () => {},
  getActiveGroup: () => null,
  cancelCurrentActiveGroup: () => {},
}))

vi.mock('../../voice/components/ReadAloudButton', () => ({
  stopActiveReadAloud: () => {},
  ReadAloudButton: () => null,
}))

vi.mock('../buildChildren', () => ({ buildChildren: () => [] }))

vi.mock('../../voice-commands', () => ({
  useVoiceLifecycleStore: (selector?: (s: object) => unknown) =>
    selector ? selector({}) : {},
}))

vi.mock('../../images/store', () => ({
  useImagesStore: (selector?: (s: object) => unknown) =>
    selector ? selector({ active: null }) : {},
}))

vi.mock('../../voice/infrastructure/useReportBounds', () => ({
  useReportBounds: () => () => {},
}))

// ---------------------------------------------------------------------------
// Child components — render as inert null nodes so we sidestep their own
// hook trees and only exercise the resolve effect.

vi.mock('../MessageList', () => ({ MessageList: () => null }))
vi.mock('../ChatInput', () => ({ ChatInput: () => null }))
vi.mock('../cockpit/CockpitBar', () => ({ CockpitBar: () => null }))
vi.mock('../ContextStatusPill', () => ({ ContextStatusPill: () => null }))
vi.mock('../AttachmentStrip', () => ({ AttachmentStrip: () => null }))
vi.mock('../UploadBrowserPanel', () => ({ UploadBrowserPanel: () => null }))
vi.mock('../BookmarkModal', () => ({ BookmarkModal: () => null }))
vi.mock('../ChatBookmarkList', () => ({ ChatBookmarkList: () => null }))
vi.mock('../JournalBadge', () => ({ JournalBadge: () => null }))
vi.mock('../KnowledgeDropdown', () => ({ KnowledgeDropdown: () => null }))
vi.mock('../../artefact/ArtefactRail', () => ({ ArtefactRail: () => null }))
vi.mock('../../artefact/ArtefactSidebar', () => ({ ArtefactSidebar: () => null }))
vi.mock('../../artefact/ArtefactOverlay', () => ({ ArtefactOverlay: () => null }))
vi.mock('../../voice/components/TranscriptionOverlay', () => ({
  TranscriptionOverlay: () => null,
}))
vi.mock('../../voice/components/ConversationModeButton', () => ({
  ConversationModeButton: () => null,
}))
vi.mock('../../voice/components/HoldToKeepTalking', () => ({
  HoldToKeepTalking: () => null,
}))
vi.mock('../../../core/components/symbols', () => ({
  CollegeIcon: () => null,
}))

// ---------------------------------------------------------------------------

// Import after mocks are in place.
import { ChatView } from '../ChatView'
import { chatApi } from '../../../core/api/chat'

function OutletShell() {
  return (
    <Outlet
      context={{
        openPersonaOverlay: () => {},
        openModal: () => {},
      }}
    />
  )
}

interface HarnessProps {
  persona: PersonaDto | null
}

function Harness({ persona }: HarnessProps) {
  return (
    <MemoryRouter initialEntries={['/chat/p1?new=1']}>
      <Routes>
        <Route element={<OutletShell />}>
          <Route path="/chat/:personaId" element={<ChatView persona={persona} />} />
          <Route
            path="/chat/:personaId/:sessionId"
            element={<ChatView persona={persona} />}
          />
        </Route>
      </Routes>
    </MemoryRouter>
  )
}

describe('ChatView neutral-trigger persona race', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('waits for persona before creating a forceNew session', async () => {
    const { rerender } = render(<Harness persona={null} />)

    // Allow microtasks/timers a tick — if the bug regresses, the
    // resolve effect would have called createSession by now.
    await new Promise((r) => setTimeout(r, 20))
    expect(chatApi.createSession).not.toHaveBeenCalled()

    // Persona arrives with a default project — the dep array re-runs
    // the effect and the create call should now go out exactly once.
    rerender(
      <Harness
        persona={
          {
            id: 'p1',
            default_project_id: 'proj-1',
          } as unknown as PersonaDto
        }
      />,
    )

    await waitFor(() =>
      expect(chatApi.createSession).toHaveBeenCalledTimes(1),
    )
    expect(chatApi.createSession).toHaveBeenCalledWith('p1', 'proj-1')
  })
})
