import { CockpitButton } from '../CockpitButton'
import { useConversationModeStore } from '@/features/voice/stores/conversationModeStore'

type Props = {
  canEnterLive: boolean
  disabledReason: 'no-voice' | 'not-allowed' | null
}

export function LiveButton({ canEnterLive, disabledReason }: Props) {
  const active = useConversationModeStore((s) => s.active)
  const enter = useConversationModeStore((s) => s.enter)
  const exit = useConversationModeStore((s) => s.exit)

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

  return (
    <CockpitButton
      icon="🎙"
      state={active ? 'active' : 'idle'}
      accent="green"
      label={active ? 'Live · on' : 'Live · off'}
      onClick={() => (active ? exit() : enter())}
      panel={
        <div className="text-white/80">
          <div className="font-semibold text-[#4ade80] mb-1">Continuous voice mode</div>
          <p className="text-xs leading-relaxed">
            Hands-free conversation. The mic stays open, the assistant speaks answers
            aloud. You can interrupt by clicking the voice button. Best for long sessions.
          </p>
        </div>
      }
    />
  )
}
