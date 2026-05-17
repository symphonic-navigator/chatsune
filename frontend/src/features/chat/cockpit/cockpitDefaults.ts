import type { ChatSessionExtras } from '@/core/api/chat'
import type { ResolvedCapabilities } from '@/core/types/llm'

/**
 * Compute initial cockpit extras from a model's capability. Mirrors the
 * backend ``default_extras_for_capability`` (spec §4.5) so the cockpit can
 * hydrate sensibly when the session document doesn't yet carry an
 * ``extras`` value (legacy sessions, freshly-created sessions before the
 * first PATCH lands).
 *
 * Defaults table:
 *  - ``no_reasoning``     → tools on iff supported, reasoning off
 *  - ``always_on, mutex`` → reasoning on; tools off (mutex)
 *  - ``always_on``        → reasoning on, tools on (effort = default)
 *  - ``optional, mutex``  → tools on, reasoning off (mutex pref: tools)
 *  - ``optional``         → both on (effort = default)
 */
export function defaultExtrasForCapability(
  capability: ResolvedCapabilities,
): ChatSessionExtras {
  const reasoning = capability.reasoning
  const tools = capability.tools
  const hasMutex = tools.exclusive_with_reasoning
  const toolsSupported = tools.supported

  // Replay-tool-history defaults to ``true`` everywhere — the on-disk
  // shape matches the backend's ``ChatSessionExtras.replay_tool_history
  // = True`` default. See INS-049 / spec
  // ``2026-05-17-replay-tool-history-per-turn-flag-design.md``.
  if (reasoning.kind === 'no_reasoning') {
    return {
      tools_enabled: toolsSupported,
      reasoning_mode: 'off',
      reasoning_effort: null,
      replay_tool_history: true,
    }
  }
  if (reasoning.kind === 'always_on') {
    const effort = reasoning.effort?.default_bucket ?? null
    return {
      tools_enabled: toolsSupported && !hasMutex,
      reasoning_mode: 'on',
      reasoning_effort: effort,
      replay_tool_history: true,
    }
  }
  // optional
  if (hasMutex) {
    return {
      tools_enabled: toolsSupported,
      reasoning_mode: 'off',
      reasoning_effort: null,
      replay_tool_history: true,
    }
  }
  const effort = reasoning.effort?.default_bucket ?? null
  return {
    tools_enabled: toolsSupported,
    reasoning_mode: 'on',
    reasoning_effort: effort,
    replay_tool_history: true,
  }
}
