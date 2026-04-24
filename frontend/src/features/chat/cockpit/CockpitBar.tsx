import { useState } from 'react'
import { useViewport } from '@/core/hooks/useViewport'
import { ThinkingButton } from './buttons/ThinkingButton'
import { ToolsButton } from './buttons/ToolsButton'
import type { ToolGroup } from './buttons/ToolsButton'
import { IntegrationsButton } from './buttons/IntegrationsButton'
import { VoiceButton } from './buttons/VoiceButton'
import { LiveButton } from './buttons/LiveButton'
import { AttachButton, CameraButton, BrowseButton } from './buttons/AttachmentButtons'
import { MobileInfoModal } from './MobileInfoModal'
import { CockpitButton } from './CockpitButton'

type VoiceSummary = {
  ttsProvider: string
  voice: string
  mode: string
  sttProvider: string
  sensitivity: string
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

  return (
    <div className="flex flex-wrap items-center gap-1.5 px-3 py-2 bg-[#0f0d16] rounded-lg">
      <AttachButton onClick={props.handlers.attach} />
      {isMobile && <CameraButton onClick={props.handlers.camera} />}
      <BrowseButton onClick={props.handlers.browse} />
      <Sep />
      <ThinkingButton
        sessionId={props.sessionId}
        modelSupportsReasoning={props.modelSupportsReasoning}
        personaReasoningDefault={props.personaReasoningDefault}
      />
      <ToolsButton
        sessionId={props.sessionId}
        availableGroups={props.availableToolGroups}
      />
      <Sep />
      <IntegrationsButton activePersonaIntegrationIds={props.activePersonaIntegrationIds} />
      <Sep />
      <VoiceButton
        sessionId={props.sessionId}
        personaHasVoice={props.personaHasVoice}
        voiceSummary={props.voiceSummary}
        onOpenVoiceSettings={props.handlers.openPersonaVoiceSettings}
      />
      <Sep />
      <LiveButton
        canEnterLive={props.liveAvailability.canEnterLive}
        disabledReason={props.liveAvailability.reason}
      />
      {isMobile && (
        <>
          <Sep />
          <CockpitButton
            icon="ⓘ"
            state="idle"
            accent="neutral"
            label="Status info"
            onClick={() => setInfoOpen(true)}
          />
        </>
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
              statusLine: `${props.availableToolGroups.length} available`,
              active: props.availableToolGroups.length > 0,
              body: (
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
                  <div className="text-white/50">Mode</div><div>{props.voiceSummary.mode}</div>
                  <div className="text-white/50">STT</div><div>{props.voiceSummary.sttProvider}</div>
                  <div className="text-white/50">Sensitivity</div><div>{props.voiceSummary.sensitivity}</div>
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
