import { useState } from 'react'
import { useViewport } from '@/core/hooks/useViewport'
import { BargingToggleButton } from './buttons/BargingToggleButton'
import { useConversationModeStore } from '@/features/voice/stores/conversationModeStore'
import { ReasoningToolsCluster } from './ReasoningToolsCluster'
import type { ToolGroup } from './buttons/ToolsButton'
import { IntegrationsButton } from './buttons/IntegrationsButton'
import { VoiceButton } from './buttons/VoiceButton'
import { LiveButton } from './buttons/LiveButton'
import { AttachButton, CameraButton, BrowseButton } from './buttons/AttachmentButtons'
import { ImageButton } from '@/features/images/cockpit/ImageButton'
import { MobileInfoModal } from './MobileInfoModal'
import { CockpitButton } from './CockpitButton'
import { CockpitGroupButton } from './CockpitGroupButton'
import { useCockpitSession, useCockpitStore } from './cockpitStore'
import { useEmojiPickerStore } from '../emojiPickerStore'
import type { ResolvedCapabilities } from '@/core/types/llm'
import type { ChatSessionExtras } from '@/core/api/chat'

type VoiceSummary = {
  ttsProvider: string
  voice: string
  narratorVoice: string | null
  mode: string
  sttProvider: string
  vadThreshold: string
} | null

type Props = {
  sessionId: string
  /**
   * Resolved per-model capability (reasoning kind, effort buckets, tool
   * support, mutex flag). Drives the ThinkingButton / ToolsButton render
   * states inside ``ReasoningToolsCluster``. ``null`` while the model
   * meta is still loading — the cluster renders a no-op placeholder so
   * the row layout stays stable.
   */
  capability: ResolvedCapabilities | null
  availableToolGroups: ToolGroup[]
  activePersonaIntegrationIds: string[]
  personaHasVoice: boolean
  voiceSummary: VoiceSummary
  liveAvailability: { canEnterLive: boolean; reason: 'no-voice' | 'not-allowed' | null }
  // ``false`` when the persona's effective vision capability is missing —
  // disables the camera button (image-only) and surfaces a tooltip
  // explaining how to unblock. The attach + browse buttons stay enabled
  // because they may be used for non-image files (PDFs, text). When
  // omitted, the buttons behave as if uploads are allowed (backwards
  // compatible default for any future caller).
  canSendImages?: boolean
  imageBlockedReason?: string
  handlers: {
    attach: () => void
    camera: () => void
    browse: () => void
    openPersonaVoiceSettings?: () => void
    openLlmProviderSettings?: () => void
  }
}

function Sep() {
  return <span className="px-1 text-white/20">│</span>
}

// Permissive fallback used while ``capability`` is still loading. Keeps the
// row layout stable without claiming any specific feature support — both
// buttons render in their disabled states until the real capability arrives.
const LOADING_CAPABILITY: ResolvedCapabilities = {
  reasoning: { kind: 'no_reasoning', effort: null, default_on: false },
  tools: { supported: false, exclusive_with_reasoning: false },
  first_class_support: false,
}

export function CockpitBar(props: Props) {
  const { isMobile } = useViewport()
  const liveActive = useConversationModeStore((s) => s.active)
  const [infoOpen, setInfoOpen] = useState(false)
  const cockpit = useCockpitSession(props.sessionId)
  const isPickerOpen = useEmojiPickerStore((s) => s.isOpen)
  const updateExtras = useCockpitStore((s) => s.updateExtras)

  const cameraDisabled = props.canSendImages === false
  const attachGroupChildren = (
    <>
      <AttachButton onClick={props.handlers.attach} />
      <CameraButton
        onClick={props.handlers.camera}
        disabled={cameraDisabled}
        disabledReason={cameraDisabled ? props.imageBlockedReason : undefined}
      />
      <BrowseButton onClick={props.handlers.browse} />
    </>
  )

  // No-op fallback when no llm-providers handler was provided. Keeps the
  // ImageButton prop required (so callers can't forget about the disabled
  // state) without forcing every consumer to wire it up immediately.
  const openLlmProviders = props.handlers.openLlmProviderSettings ?? (() => {})

  const capability = props.capability ?? LOADING_CAPABILITY
  // Permissive default extras while the session is still hydrating — keeps
  // the buttons in their "off" state without throwing. Once ``cockpit``
  // resolves the cluster re-renders with the real values.
  const extras: ChatSessionExtras = cockpit?.extras ?? {
    tools_enabled: false,
    reasoning_mode: 'off',
    reasoning_effort: null,
  }

  const handleClusterUpdate = async (patch: Partial<ChatSessionExtras>) => {
    await updateExtras(props.sessionId, patch)
  }

  const cluster = (
    <ReasoningToolsCluster
      capability={capability}
      extras={extras}
      availableGroups={props.availableToolGroups}
      onUpdate={handleClusterUpdate}
    />
  )

  const toolsActive = Boolean(cockpit?.tools) || props.activePersonaIntegrationIds.length > 0

  // On mobile the Tools button is folded into a group with Image and
  // Integrations. The cluster's two buttons render side-by-side, so we
  // split them visually by extracting just the ToolsButton portion via
  // ``ReasoningToolsCluster`` and putting the Thinking button outside the
  // group. Easiest implementation: render the whole cluster on the row
  // and let the group's icon visualise the group state independently.
  const toolsGroupChildren = (
    <>
      <ImageButton sessionId={props.sessionId} onOpenLlmProviders={openLlmProviders} />
      <IntegrationsButton activePersonaIntegrationIds={props.activePersonaIntegrationIds} />
    </>
  )

  return (
    <div className={`flex flex-wrap items-center py-2 bg-[#0f0d16] rounded-lg ${isMobile ? 'gap-1 px-2' : 'gap-1.5 px-3'}`}>
      {isMobile ? (
        <CockpitGroupButton icon="📎" label="Attach, camera, browse">
          {attachGroupChildren}
        </CockpitGroupButton>
      ) : (
        <>
          <AttachButton onClick={props.handlers.attach} />
          <BrowseButton onClick={props.handlers.browse} />
          <Sep />
        </>
      )}
      {cluster}
      {isMobile ? (
        <CockpitGroupButton
          icon="🔧"
          label="Image and integrations"
          hasActiveChild={toolsActive}
        >
          {toolsGroupChildren}
        </CockpitGroupButton>
      ) : (
        <>
          <ImageButton sessionId={props.sessionId} onOpenLlmProviders={openLlmProviders} />
          <Sep />
          <IntegrationsButton activePersonaIntegrationIds={props.activePersonaIntegrationIds} />
          <Sep />
        </>
      )}
      <VoiceButton
        sessionId={props.sessionId}
        personaHasVoice={props.personaHasVoice}
        voiceSummary={props.voiceSummary}
        onOpenVoiceSettings={props.handlers.openPersonaVoiceSettings}
      />
      {!isMobile && <Sep />}
      <LiveButton
        sessionId={props.sessionId}
        canEnterLive={props.liveAvailability.canEnterLive}
        disabledReason={props.liveAvailability.reason}
      />
      {!isMobile && liveActive && (
        <>
          <Sep />
          <BargingToggleButton />
        </>
      )}
      {isMobile && (
        <CockpitButton
          icon="😊"
          state={isPickerOpen ? 'active' : 'idle'}
          accent="neutral"
          label="Insert emoji"
          onClick={() => useEmojiPickerStore.getState().toggle()}
        />
      )}
      {isMobile && (
        liveActive ? (
          <BargingToggleButton />
        ) : (
          <CockpitButton
            icon="ⓘ"
            state="idle"
            accent="neutral"
            label="Status info"
            onClick={() => setInfoOpen(true)}
          />
        )
      )}

      {isMobile && (
        <MobileInfoModal
          open={infoOpen}
          onClose={() => setInfoOpen(false)}
          sections={[
            {
              id: 'thinking',
              icon: '💡',
              title: 'Thinking',
              statusLine: extras.reasoning_mode === 'on' ? 'on' : 'off',
              active: extras.reasoning_mode === 'on',
              body: (
                <p>
                  The model thinks before answering. Good for complex questions.
                </p>
              ),
            },
            {
              id: 'tools',
              icon: '🔧',
              title: 'Tools',
              statusLine: cockpit?.tools
                ? `on · ${props.availableToolGroups.length} available`
                : 'off',
              active: Boolean(cockpit?.tools),
              body: cockpit?.tools ? (
                <ul className="space-y-1">
                  {props.availableToolGroups.map((g) => (
                    <li key={g.id}>
                      <span className="text-white/40 uppercase tracking-wider text-[10px] mr-2">
                        {g.kind}
                      </span>
                      {g.label}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-white/50">
                  Tools are off for this chat. Toggle on to let the model call them.
                </p>
              ),
            },
            {
              id: 'integrations',
              icon: '🔌',
              title: 'Integrations',
              statusLine: `${props.activePersonaIntegrationIds.length} active`,
              active: props.activePersonaIntegrationIds.length > 0,
              body: <p>Use the button above for stop controls.</p>,
            },
            {
              id: 'voice',
              icon: '🔊',
              title: 'Voice',
              statusLine: props.personaHasVoice ? 'ready' : 'none',
              active: props.personaHasVoice,
              body: props.voiceSummary ? (
                <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                  <div className="text-white/50">TTS</div><div>{props.voiceSummary.ttsProvider}</div>
                  <div className="text-white/50">Voice</div><div>{props.voiceSummary.voice}</div>
                  {props.voiceSummary.narratorVoice && (
                    <>
                      <div className="text-white/50">Narrator</div><div>{props.voiceSummary.narratorVoice}</div>
                    </>
                  )}
                  <div className="text-white/50">Mode</div><div>{props.voiceSummary.mode}</div>
                  <div className="text-white/50">STT</div><div>{props.voiceSummary.sttProvider}</div>
                  <div className="text-white/50">VAD Threshold</div><div>{props.voiceSummary.vadThreshold}</div>
                </div>
              ) : (
                <p>No voice configured on this persona.</p>
              ),
            },
            {
              id: 'live',
              icon: '🎙',
              title: 'Live',
              statusLine: props.liveAvailability.canEnterLive ? 'available' : 'unavailable',
              active: false,
              body: (
                <p>
                  Hands-free conversation. Mic stays open; assistant speaks answers aloud.
                </p>
              ),
            },
          ]}
        />
      )}
    </div>
  )
}
