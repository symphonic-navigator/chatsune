import { eventBus } from '../../../core/websocket/eventBus'
import type { CommandSpec, CommandResponse } from '../types'

/**
 * Built-in debug command. Emits a frontend-internal event carrying the
 * normalised body; a small mounted component pops a window.alert in
 * response. Proves the full pipeline end-to-end with the smallest
 * possible consumer.
 *
 * Topic naming convention for future per-command frontend events:
 * 'voice_command.<trigger>'. Frontend-only — not added to
 * shared/topics.py because this signal does not cross the WS boundary.
 */
export const debugCommand: CommandSpec = {
  trigger: 'debug',
  onTriggerWhilePlaying: 'resume',
  source: 'core',
  execute: async (body: string): Promise<CommandResponse> => {
    eventBus.emit({
      id: `voice-cmd-debug-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      type: 'voice_command.debug',
      sequence: '0',
      scope: 'frontend',
      correlation_id: `voice-cmd-debug-${Date.now()}`,
      timestamp: new Date().toISOString(),
      payload: { body },
    })
    return {
      level: 'info',
      spokenText: 'Debug command received.',
      displayText: `Debug: '${body || '(empty)'}'`,
    }
  },
}
