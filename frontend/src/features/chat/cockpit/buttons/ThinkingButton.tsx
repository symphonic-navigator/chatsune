import { CockpitButton } from '../CockpitButton'
import { useCockpitSession, useCockpitStore } from '../cockpitStore'

type Props = {
  sessionId: string
  modelSupportsReasoning: boolean
}

export function ThinkingButton({ sessionId, modelSupportsReasoning }: Props) {
  const cockpit = useCockpitSession(sessionId)
  const setThinking = useCockpitStore((s) => s.setThinking)
  const on = cockpit?.thinking ?? false

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

  return (
    <CockpitButton
      icon="💡"
      state={on ? 'active' : 'idle'}
      accent="gold"
      label={on ? 'Thinking · on' : 'Thinking · off'}
      onClick={() => setThinking(sessionId, !on)}
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
