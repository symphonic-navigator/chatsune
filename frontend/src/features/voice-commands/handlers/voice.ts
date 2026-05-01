import { useVoiceLifecycleStore } from '../voiceLifecycleStore'
import type { CommandSpec, CommandResponse } from '../types'

const PAUSE_SYNONYMS  = new Set(['pause', 'off', 'of'])
const ACTIVE_SYNONYMS = new Set(['continue', 'on', 'resume'])
const STATUS_SYNONYMS = new Set(['status', 'state'])

const PAUSE_TOAST  = 'Paused — say "voice on" to resume.'
const ACTIVE_TOAST = 'Listening — say "voice off" to pause.'

/** True if `token` is a recognised voice subcommand. Used by the dispatcher's
 *  strict-reject pre-check (see dispatcher.ts). Exported deliberately. */
export function isKnownVoiceSub(token: string): boolean {
  return PAUSE_SYNONYMS.has(token) || ACTIVE_SYNONYMS.has(token) || STATUS_SYNONYMS.has(token)
}

/**
 * Built-in voice-lifecycle command. Single trigger `voice`, three actions
 * selected by the first token of the body (synonym sets above):
 *
 *  - pause   → setPause(), off cue, PAUSE_TOAST, default abandon
 *  - active  → setActive(), on cue, ACTIVE_TOAST, default abandon (no-op when
 *              entering from paused — no Group exists); already-active path
 *              returns 'resume' override so the persona is not interrupted.
 *  - status  → no transition, current-state cue + toast, always 'resume'.
 */
export const voiceCommand: CommandSpec = {
  trigger: 'voice',
  onTriggerWhilePlaying: 'abandon',
  source: 'core',
  execute: async (body: string): Promise<CommandResponse> => {
    const lifecycle = useVoiceLifecycleStore.getState()
    const sub = body.trim().split(/\s+/)[0] ?? ''

    if (PAUSE_SYNONYMS.has(sub)) {
      lifecycle.setPause()
      return { level: 'success', cue: 'off', displayText: PAUSE_TOAST }
    }

    if (ACTIVE_SYNONYMS.has(sub)) {
      if (lifecycle.state === 'active') {
        return {
          level: 'info',
          cue: 'on',
          displayText: ACTIVE_TOAST,
          onTriggerWhilePlaying: 'resume',
        }
      }
      lifecycle.setActive()
      return { level: 'success', cue: 'on', displayText: ACTIVE_TOAST }
    }

    if (STATUS_SYNONYMS.has(sub)) {
      const paused = lifecycle.state === 'paused'
      return {
        level: 'info',
        cue: paused ? 'off' : 'on',
        displayText: paused ? PAUSE_TOAST : ACTIVE_TOAST,
        onTriggerWhilePlaying: 'resume',
      }
    }

    return {
      level: 'error',
      displayText: `Unknown voice command: '${sub}'.`,
      onTriggerWhilePlaying: 'resume',
    }
  },
}
