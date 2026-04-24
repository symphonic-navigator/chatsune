import type { ReactNode } from 'react'
import { CockpitButton } from '../CockpitButton'
import { useCockpitSession, useCockpitStore } from '../cockpitStore'
import { useVoicePipeline } from '@/features/voice/stores/voicePipelineStore'
import { useConversationModeStore } from '@/features/voice/stores/conversationModeStore'
import { useIsReadingAloud, stopActiveReadAloud } from '@/features/voice/components/ReadAloudButton'
import { usePhase } from '@/features/voice/usePhase'
import { getActiveGroup } from '@/features/chat/responseTaskGroup'
import { deriveVoiceUIState } from './_voiceState'
import type { VoiceUIState } from './_voiceState'

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
  onOpenVoiceSettings?: () => void
}

export function VoiceButton({ sessionId, personaHasVoice, voiceSummary, onOpenVoiceSettings }: Props) {
  const cockpit = useCockpitSession(sessionId)
  const setAutoRead = useCockpitStore((s) => s.setAutoRead)
  const stopPlayback = useVoicePipeline((s) => s.stopPlayback)
  const liveActive = useConversationModeStore((s) => s.active)
  const micMuted = useConversationModeStore((s) => s.micMuted)
  const setMicMuted = useConversationModeStore((s) => s.setMicMuted)
  const isReadingAloud = useIsReadingAloud()
  const livePhase = usePhase()

  // Two distinct playback paths feed this button: the live ResponseTaskGroup
  // (usePhase === 'speaking' — Group in streaming/tailing) in continuous-voice
  // mode, and the read-aloud path (auto-read or manual ReadAloudButton) in
  // normal chat. Either one puts the cockpit into the "stop playback" state.
  const ttsPlaying = isReadingAloud || (liveActive && livePhase === 'speaking')
  const autoRead = cockpit?.autoRead ?? false

  const ui = deriveVoiceUIState({
    personaHasVoice,
    liveMode: liveActive,
    ttsPlaying,
    autoRead,
    micMuted,
  })

  // Emoji for every state except the mic pair — there we render an SVG so
  // muted is unambiguously the same mic shape plus a diagonal slash. Keeping
  // the glyph identical across on/off states is what makes the muted state
  // instantly readable; swapping emojis (🎤 vs 🎙) drops that signal.
  const iconFor: Record<Exclude<VoiceUIState['kind'], 'live-mic-on' | 'live-mic-muted'>, ReactNode> = {
    'disabled': '🔈',
    'normal-off': '🔈',
    'normal-on': '🔊',
    'normal-playing': '⏹',
    'live-playing': '⏹',
  }
  const iconNode: ReactNode =
    ui.kind === 'live-mic-on'     ? <MicIcon muted={false} /> :
    ui.kind === 'live-mic-muted'  ? <MicIcon muted={true}  /> :
    iconFor[ui.kind]

  const stopAnyPlayback = () => {
    // Three playback paths to silence, in order of specificity:
    //  1. Read-aloud (normal chat, manual or auto) — clears the module-local
    //     active-reader state alongside the audio.
    //  2. Live-mode ResponseTaskGroup — cancel with 'user-stop' so the server
    //     tears down LLM generation and the synth/playback children drain.
    //  3. Fall-through stopAll on any audio that slipped through both paths
    //     (belt-and-suspenders).
    stopActiveReadAloud()
    const group = getActiveGroup()
    if (group) group.cancel('user-stop')
    stopPlayback()
  }

  const onClick = () => {
    switch (ui.kind) {
      case 'normal-off':      return setAutoRead(sessionId, true)
      case 'normal-on':       return setAutoRead(sessionId, false)
      case 'normal-playing':  return stopAnyPlayback()
      case 'live-mic-on':     return setMicMuted(true)
      case 'live-mic-muted':  return setMicMuted(false)
      case 'live-playing':    return stopAnyPlayback()
      case 'disabled':        return
    }
  }

  if (ui.kind === 'disabled') {
    return (
      <CockpitButton
        icon={iconFor[ui.kind]}
        state="disabled"
        accent="blue"
        label={onOpenVoiceSettings ? 'Open voice settings' : 'Voice unavailable'}
        onClick={onOpenVoiceSettings}
        panel={
          <div className="text-white/70">
            <p>
              This persona has no voice. Pick a TTS provider and a voice in persona settings.
            </p>
            {onOpenVoiceSettings && (
              <p className="mt-2 text-[11px] text-[#60a5fa]">Click to open settings →</p>
            )}
          </div>
        }
      />
    )
  }

  const stateClass: 'playback' | 'idle' | 'active' =
    ui.kind === 'normal-playing' || ui.kind === 'live-playing' ? 'playback' :
    (ui.kind === 'normal-off' || ui.kind === 'live-mic-muted') ? 'idle' : 'active'

  return (
    <CockpitButton
      icon={iconNode}
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

/**
 * Microphone glyph shared by mic-on and mic-muted states. The muted variant
 * overlays a diagonal slash — same shape, same size, so the user reads the
 * difference at a glance instead of parsing two distinct icons.
 */
function MicIcon({ muted }: { muted: boolean }) {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <rect x="6" y="2" width="4" height="7" rx="2" fill="currentColor" />
      <path
        d="M4 7.5V8a4 4 0 0 0 8 0v-.5"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
      />
      <path d="M8 12v2" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
      <path d="M5.5 14h5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
      {muted && (
        <path
          d="M2 2 14 14"
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinecap="round"
        />
      )}
    </svg>
  )
}
