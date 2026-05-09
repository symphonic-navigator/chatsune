import type { ResolvedCapabilities } from '@/core/types/llm'
import type { ChatSessionExtras } from '@/core/api/chat'
import { ThinkingButton } from './buttons/ThinkingButton'
import { ToolsButton, type ToolGroup } from './buttons/ToolsButton'

type Props = {
  capability: ResolvedCapabilities
  extras: ChatSessionExtras
  availableGroups?: ToolGroup[]
  /**
   * Persist a partial update to the session ``extras``. The cluster never
   * emits a partial that violates the model's mutex constraint — when both
   * sides need to change in lockstep (e.g. enabling tools on a mutex model
   * that has reasoning on), both fields are sent in the same patch so the
   * backend sees a consistent state.
   */
  onUpdate: (patch: Partial<ChatSessionExtras>) => Promise<void>
}

/**
 * Owns the mutual-exclusion coordination between the Thinking and Tools
 * cockpit buttons. Lives one level above the buttons so neither needs to
 * know about the other — they are pure presentational components driven
 * by the resolved per-model capability and the session's extras.
 *
 * Mutex rule: when ``capability.tools.exclusive_with_reasoning`` is true,
 * activating one feature must deactivate the other in the same patch.
 * On non-mutex models (or when toggling something off), only the directly
 * touched field is included in the patch — keeping the wire payload
 * minimal and the optimistic update narrow.
 */
export function ReasoningToolsCluster({
  capability,
  extras,
  availableGroups = [],
  onUpdate,
}: Props) {
  const mutex = capability.tools.exclusive_with_reasoning

  const handleReasoning = async (mode: 'off' | 'on', effort: string | null) => {
    const patch: Partial<ChatSessionExtras> = {
      reasoning_mode: mode,
      reasoning_effort: effort,
    }
    if (mode === 'on' && mutex && extras.tools_enabled) {
      patch.tools_enabled = false
    }
    await onUpdate(patch)
  }

  const handleTools = async (next: boolean) => {
    const patch: Partial<ChatSessionExtras> = { tools_enabled: next }
    if (next && mutex && extras.reasoning_mode === 'on') {
      patch.reasoning_mode = 'off'
      patch.reasoning_effort = null
    }
    await onUpdate(patch)
  }

  return (
    <>
      <ThinkingButton
        reasoning={capability.reasoning}
        mode={extras.reasoning_mode}
        effort={extras.reasoning_effort}
        onChange={handleReasoning}
      />
      <ToolsButton
        tools={capability.tools}
        enabled={extras.tools_enabled}
        availableGroups={availableGroups}
        onChange={handleTools}
      />
    </>
  )
}
