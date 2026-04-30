import { useEffect } from 'react'
import { eventBus } from '../../core/websocket/eventBus'

/**
 * Mount-once consumer for the debug voice command's event.
 *
 * Deliberately ugly — this is a debug affordance to prove the voice-command
 * pipeline end-to-end, not a UX feature. Replace or remove when the
 * pipeline is exercised by real commands (companion, hue, …).
 */
export function VoiceCommandDebugAlert(): null {
  useEffect(() => {
    const off = eventBus.on('voice_command.debug', (event) => {
      const body = (event.payload as { body?: string }).body ?? ''
      window.alert(`Voice debug command body: '${body || '(empty)'}'`)
    })
    return off
  }, [])
  return null
}
