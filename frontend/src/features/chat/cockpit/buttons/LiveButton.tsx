import { CockpitButton } from '../CockpitButton'
import { useCockpitSession, useCockpitStore } from '../cockpitStore'
import { useConversationModeStore } from '@/features/voice/stores/conversationModeStore'
import { stopActiveReadAloud } from '@/features/voice/components/ReadAloudButton'

type Props = {
  sessionId: string
  canEnterLive: boolean
  disabledReason: 'no-voice' | 'not-allowed' | null
}

export function LiveButton({ sessionId, canEnterLive, disabledReason }: Props) {
  const active = useConversationModeStore((s) => s.active)
  const enter = useConversationModeStore((s) => s.enter)
  const exit = useConversationModeStore((s) => s.exit)
  const cockpit = useCockpitSession(sessionId)
  const setAutoRead = useCockpitStore((s) => s.setAutoRead)
  const clearAutoReadRequest = useCockpitStore((s) => s.clearAutoReadRequest)

  if (!canEnterLive) {
    return (
      <CockpitButton
        icon="🎙"
        state="disabled"
        accent="green"
        label="Live mode unavailable"
        panel={
          <p className="text-white/70">
            {disabledReason === 'no-voice'
              ? 'Live mode needs TTS and STT on the persona.'
              : 'Live mode is not enabled for your account.'}
          </p>
        }
      />
    )
  }

  const handleClick = () => {
    if (active) {
      exit()
      return
    }
    // Entering Live mode: silence and disarm the Read-Aloud pipeline so it
    // does not race the live ResponseTaskGroup for audio output.
    if (cockpit?.autoRead) {
      void setAutoRead(sessionId, false)
    }
    clearAutoReadRequest()
    stopActiveReadAloud()
    enter()
  }

  return (
    <CockpitButton
      icon="🎙"
      state={active ? 'active' : 'idle'}
      accent="green"
      label={active ? 'Voice chat · on' : 'Voice chat · off'}
      onClick={handleClick}
      panel={
        <div className="text-white/80">
          <div className="font-semibold text-[#4ade80] mb-1">Voice chat</div>
          <p className="text-xs leading-relaxed">
            Hands-free conversation. The mic stays open, the assistant speaks answers
            aloud. You can interrupt by clicking the voice button. Best for long sessions.
          </p>
        </div>
      }
    />
  )
}
