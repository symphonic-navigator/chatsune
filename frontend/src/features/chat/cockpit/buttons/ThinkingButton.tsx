import { CockpitButton } from '../CockpitButton'
import { useChatStore } from '@/core/store/chatStore'
import { chatApi } from '@/core/api/chat'

type Props = {
  sessionId: string
  modelSupportsReasoning: boolean
  personaReasoningDefault: boolean
}

/**
 * Thinking toggle. Source of truth is `chatStore.reasoningOverride` because
 * the conversation-mode hook writes there when entering live chat (forcing
 * reasoning off) and restoring on exit; the cockpit has to see the same
 * value. `null` in the override means "use persona default".
 */
export function ThinkingButton({ sessionId, modelSupportsReasoning, personaReasoningDefault }: Props) {
  const reasoningOverride = useChatStore((s) => s.reasoningOverride)
  const setReasoningOverride = useChatStore((s) => s.setReasoningOverride)

  if (!modelSupportsReasoning) {
    return (
      <CockpitButton
        icon="💡"
        state="disabled"
        accent="gold"
        label="Thinking disabled"
        panel={<p className="text-white/70">This model does not support reasoning.</p>}
      />
    )
  }

  const on = reasoningOverride !== null ? reasoningOverride : personaReasoningDefault

  const toggle = async () => {
    const next = !on
    // Optimistic update so the UI feels instant; revert on API error.
    const prev = reasoningOverride
    setReasoningOverride(next)
    try {
      await chatApi.updateSessionReasoning(sessionId, next)
    } catch (e) {
      setReasoningOverride(prev)
      throw e
    }
  }

  return (
    <CockpitButton
      icon="💡"
      state={on ? 'active' : 'idle'}
      accent="gold"
      label={on ? 'Thinking · on' : 'Thinking · off'}
      onClick={() => { void toggle() }}
      panel={
        <div className="text-white/80">
          <div className="font-semibold text-[#d4af37] mb-1">
            Reasoning · {on ? 'on' : 'off'}
          </div>
          <p className="text-xs leading-relaxed">
            The model thinks before it answers. Good for complex questions.
            Some models ignore this when tools are also on.
          </p>
          <div className="mt-2 text-[10px] uppercase tracking-wider text-white/40">
            Session: remembered for this chat.
          </div>
        </div>
      }
    />
  )
}
