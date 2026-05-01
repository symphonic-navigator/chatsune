import { useVoiceLifecycleStore } from '../voiceLifecycleStore'
import type { CommandSpec, CommandResponse } from '../types'

/**
 * Built-in companion-lifecycle command. Single trigger `companion`,
 * three sub-commands selected by body content:
 *
 *  - `companion off`    — pause assistant, abandon active persona Group,
 *                          local Vosk takes over STT for the OFF state.
 *  - `companion on`     — resume normal continuous-voice operation.
 *  - `companion status` — speak the current state (cue), do not transition.
 *
 * Static onTriggerWhilePlaying default is 'abandon' (the off case). Other
 * sub-commands override per-call via CommandResponse.onTriggerWhilePlaying:
 *  - status always returns 'resume' (must never interrupt the persona);
 *  - idempotent on returns 'resume' (acknowledge but don't disturb);
 *  - error path returns 'resume' (an unknown body is no reason to abandon).
 */
export const companionCommand: CommandSpec = {
  trigger: 'companion',
  onTriggerWhilePlaying: 'abandon',
  source: 'core',
  execute: async (body: string): Promise<CommandResponse> => {
    const lifecycle = useVoiceLifecycleStore.getState()
    const sub = body.trim()

    switch (sub) {
      case 'off':
        if (lifecycle.state === 'paused') {
          // Idempotent path — defensive; under normal flow this is
          // unreachable because the OFF-state Vosk grammar omits "companion
          // off" entirely. No override needed.
          return {
            level: 'info',
            cue: 'off',
            displayText: 'Companion already off.',
          }
        }
        lifecycle.setPause()
        return {
          level: 'success',
          cue: 'off',
          displayText: 'Companion off.',
        }

      case 'on':
        if (lifecycle.state === 'active') {
          // Idempotent — the user gets audible confirmation that the
          // command was heard, but the persona must not be interrupted.
          return {
            level: 'info',
            cue: 'on',
            displayText: 'Companion already on.',
            onTriggerWhilePlaying: 'resume',
          }
        }
        lifecycle.setActive()
        // Successful OFF→ON: in OFF the persona was already abandoned,
        // so the static 'abandon' default is a no-op — no override.
        return {
          level: 'success',
          cue: 'on',
          displayText: 'Companion on.',
        }

      case 'status':
        // Status must never interrupt the persona — always override.
        return {
          level: 'info',
          cue: lifecycle.state === 'paused' ? 'off' : 'on',
          displayText: `Companion is ${lifecycle.state === 'paused' ? 'off' : 'on'}.`,
          onTriggerWhilePlaying: 'resume',
        }

      default:
        return {
          level: 'error',
          displayText: `Unknown companion command: '${sub}'.`,
          onTriggerWhilePlaying: 'resume',
        }
    }
  },
}
