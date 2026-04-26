import { useState } from 'react'
import { useViewport } from '@/core/hooks/useViewport'
import { ThinkingButton } from './buttons/ThinkingButton'
import { ToolsButton } from './buttons/ToolsButton'
import type { ToolGroup } from './buttons/ToolsButton'
import { IntegrationsButton } from './buttons/IntegrationsButton'
import { VoiceButton } from './buttons/VoiceButton'
import { LiveButton } from './buttons/LiveButton'
import { AttachButton, CameraButton, BrowseButton } from './buttons/AttachmentButtons'
import { ImageButton } from '@/features/images/cockpit/ImageButton'
import { MobileInfoModal } from './MobileInfoModal'
import { CockpitButton } from './CockpitButton'
import { CockpitGroupButton } from './CockpitGroupButton'
import { useCockpitSession } from './cockpitStore'
import { useEmojiPickerStore } from '../emojiPickerStore'

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
  modelSupportsReasoning: boolean
  personaReasoningDefault: boolean
  availableToolGroups: ToolGroup[]
  activePersonaIntegrationIds: string[]
  personaHasVoice: boolean
  voiceSummary: VoiceSummary
  liveAvailability: { canEnterLive: boolean; reason: 'no-voice' | 'not-allowed' | null }
  handlers: {
    attach: () => void
    camera: () => void
    browse: () => void
    openPersonaVoiceSettings?: () => void
  }
}

function Sep() {
  return <span className="px-1 text-white/20">│</span>
}

export function CockpitBar(props: Props) {
  const { isMobile } = useViewport()
  const [infoOpen, setInfoOpen] = useState(false)
  const cockpit = useCockpitSession(props.sessionId)
  const isPickerOpen = useEmojiPickerStore((s) => s.isOpen)

  const attachGroupChildren = (
    <>
      <AttachButton onClick={props.handlers.attach} />
      <CameraButton onClick={props.handlers.camera} />
      <BrowseButton onClick={props.handlers.browse} />
    </>
  )

  const toolsGroupChildren = (
    <>
      <ToolsButton
        sessionId={props.sessionId}
        availableGroups={props.availableToolGroups}
      />
      <ImageButton />
      <IntegrationsButton activePersonaIntegrationIds={props.activePersonaIntegrationIds} />
    </>
  )

  const toolsActive = Boolean(cockpit?.tools) || props.activePersonaIntegrationIds.length > 0

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
      <ThinkingButton
        sessionId={props.sessionId}
        modelSupportsReasoning={props.modelSupportsReasoning}
        personaReasoningDefault={props.personaReasoningDefault}
      />
      {isMobile ? (
        <CockpitGroupButton
          icon="🔧"
          label="Tools and integrations"
          hasActiveChild={toolsActive}
        >
          {toolsGroupChildren}
        </CockpitGroupButton>
      ) : (
        <>
          <ToolsButton
            sessionId={props.sessionId}
            availableGroups={props.availableToolGroups}
          />
          <ImageButton />
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
        canEnterLive={props.liveAvailability.canEnterLive}
        disabledReason={props.liveAvailability.reason}
      />
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
        <CockpitButton
          icon="ⓘ"
          state="idle"
          accent="neutral"
          label="Status info"
          onClick={() => setInfoOpen(true)}
        />
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
              statusLine: 'off',
              active: false,
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
