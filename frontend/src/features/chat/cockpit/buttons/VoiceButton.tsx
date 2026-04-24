import { CockpitButton } from '../CockpitButton'
import { useCockpitSession, useCockpitStore } from '../cockpitStore'
import { useVoicePipeline } from '@/features/voice/stores/voicePipelineStore'
import { useConversationModeStore } from '@/features/voice/stores/conversationModeStore'
import { deriveVoiceUIState, VoiceUIState } from './_voiceState'

type Props = {
  sessionId: string
  personaHasVoice: boolean
  voiceSummary: {
    ttsProvider: string
    voice: string
    mode: string
    sttProvider: string
    sensitivity: string
  } | null
}

export function VoiceButton({ sessionId, personaHasVoice, voiceSummary }: Props) {
  const cockpit = useCockpitSession(sessionId)
  const setAutoRead = useCockpitStore((s) => s.setAutoRead)
  const pipelinePhase = useVoicePipeline((s) => s.state.phase)
  const stopPlayback = useVoicePipeline((s) => s.stopPlayback)
  const liveActive = useConversationModeStore((s) => s.active)
  const micMuted = useConversationModeStore((s) => s.micMuted)
  const setMicMuted = useConversationModeStore((s) => s.setMicMuted)

  const ttsPlaying = pipelinePhase === 'speaking'
  const autoRead = cockpit?.autoRead ?? false

  const ui = deriveVoiceUIState({
    personaHasVoice,
    liveMode: liveActive,
    ttsPlaying,
    autoRead,
    micMuted,
  })

  const iconFor: Record<VoiceUIState['kind'], string> = {
    'disabled': '🔈',
    'normal-off': '🔈',
    'normal-on': '🔊',
    'normal-playing': '⏹',
    'live-mic-on': '🎤',
    'live-mic-muted': '🎙',
    'live-playing': '⏹',
  }

  const onClick = () => {
    switch (ui.kind) {
      case 'normal-off':      return setAutoRead(sessionId, true)
      case 'normal-on':       return setAutoRead(sessionId, false)
      case 'normal-playing':  return stopPlayback()
      case 'live-mic-on':     return setMicMuted(true)
      case 'live-mic-muted':  return setMicMuted(false)
      case 'live-playing':    return stopPlayback()
      case 'disabled':        return
    }
  }

  if (ui.kind === 'disabled') {
    return (
      <CockpitButton
        icon={iconFor[ui.kind]}
        state="disabled"
        accent="blue"
        label="Voice unavailable"
        panel={
          <p className="text-white/70">
            This persona has no voice. Pick a TTS provider and a voice in persona settings.
          </p>
        }
      />
    )
  }

  const stateClass: 'playback' | 'idle' | 'active' =
    ui.kind === 'normal-playing' || ui.kind === 'live-playing' ? 'playback' :
    (ui.kind === 'normal-off' || ui.kind === 'live-mic-muted') ? 'idle' : 'active'

  return (
    <CockpitButton
      icon={iconFor[ui.kind]}
      state={stateClass}
      accent="blue"
      label={labelFor(ui.kind)}
      onClick={onClick}
      panel={
        <div className="text-white/85">
          <div className="font-semibold text-[#60a5fa] mb-2">{statusFor(ui.kind, autoRead)}</div>
          {voiceSummary && (
            <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
              <div className="text-white/50">TTS</div><div>{voiceSummary.ttsProvider}</div>
              <div className="text-white/50">Voice</div><div>{voiceSummary.voice}</div>
              <div className="text-white/50">Mode</div><div>{voiceSummary.mode}</div>
              <div className="text-white/50">STT</div><div>{voiceSummary.sttProvider}</div>
              <div className="text-white/50">Sensitivity</div><div>{voiceSummary.sensitivity}</div>
            </div>
          )}
        </div>
      }
    />
  )
}

function labelFor(kind: Exclude<VoiceUIState['kind'], 'disabled'>): string {
  switch (kind) {
    case 'normal-off':     return 'Auto-read · off'
    case 'normal-on':      return 'Auto-read · on'
    case 'normal-playing': return 'Stop playback'
    case 'live-mic-on':    return 'Mic is listening'
    case 'live-mic-muted': return 'Mic is muted'
    case 'live-playing':   return 'Interrupt'
  }
}

function statusFor(kind: VoiceUIState['kind'], autoRead: boolean): string {
  if (kind === 'normal-off' || kind === 'normal-on') return `Auto-read · ${autoRead ? 'on' : 'off'}`
  if (kind === 'normal-playing') return 'Playing'
  if (kind === 'live-mic-on') return 'Mic is listening'
  if (kind === 'live-mic-muted') return 'Mic is muted'
  if (kind === 'live-playing') return 'Interrupt'
  return ''
}
