/**
 * respondToUser — render a CommandResponse to the user.
 *
 * Two parallel signals:
 *  - if response.cue is set, the corresponding tone cue plays through the
 *    dedicated cue audio channel (separate AudioContext, overlays the
 *    persona without ducking);
 *  - the toast always fires.
 *
 * Cue is the hands-free signal, toast is the visual confirmation when the
 * user happens to look. They complement each other; neither is a fallback
 * for the other.
 */

import { useNotificationStore } from '../../core/store/notificationStore'
import { playCue } from './cuePlayer'
import type { CommandResponse } from './types'

export function respondToUser(response: CommandResponse): void {
  console.debug('[VoiceCommand] response:', response)
  if (response.cue) playCue(response.cue)
  useNotificationStore.getState().addNotification({
    level: response.level,
    title: 'Voice command',
    message: response.displayText,
  })
}
