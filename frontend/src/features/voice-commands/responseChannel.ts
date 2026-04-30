/**
 * respondToUser — render a CommandResponse to the user.
 *
 * v1 implementation: log to console, push a toast through the existing
 * notification store. Part 2 will replace the body with system-voice
 * playback (cached) and fall back to this toast path when no system voice
 * is configured. The function signature is the stable contract that
 * handlers depend on across both versions — do NOT change it.
 */

import { useNotificationStore } from '../../core/store/notificationStore'
import type { CommandResponse } from './types'

export function respondToUser(response: CommandResponse): void {
  console.debug('[VoiceCommand] response:', response)
  useNotificationStore.getState().addNotification({
    level: response.level,
    title: 'Voice command',
    message: response.displayText,
  })
}
