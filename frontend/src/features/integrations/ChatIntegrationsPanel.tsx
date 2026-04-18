import { useEffect, useState } from 'react'
import { useIntegrationsStore } from './store'
import { getPlugin } from './registry'
import { useAudioPlaybackActive } from '../voice/infrastructure/useAudioPlaybackActive'
import { cancelStreamingAutoRead } from '../voice/pipeline/streamingAutoReadControl'
import { setActiveReader } from '../voice/components/ReadAloudButton'

import './plugins/lovense'
import './plugins/mistral_voice'

const MISTRAL_VOICE_ID = 'mistral_voice'

/**
 * Compact integration status & controls shown in the chat toolbar.
 * Each chip is a per-integration emergency-stop button. Clicking it calls
 * that plugin's emergencyStop. The Mistral Voice chip additionally cancels
 * in-flight TTS streaming whenever it is clicked while audio is playing.
 */
export function ChatIntegrationsPanel() {
  const definitions = useIntegrationsStore((s) => s.definitions)
  const configs = useIntegrationsStore((s) => s.configs)
  const healthStatus = useIntegrationsStore((s) => s.healthStatus)
  const setHealth = useIntegrationsStore((s) => s.setHealth)
  const audioActive = useAudioPlaybackActive()
  const [pending, setPending] = useState<Record<string, boolean>>({})

  const enabledDefs = definitions.filter((d) => configs[d.id]?.enabled)

  // Run health checks on mount and every 30 seconds
  useEffect(() => {
    if (enabledDefs.length === 0) return

    async function checkAll() {
      for (const d of enabledDefs) {
        const plugin = getPlugin(d.id)
        const config = configs[d.id]?.config ?? {}
        if (plugin?.healthCheck) {
          try {
            const status = await plugin.healthCheck(config)
            setHealth(d.id, status)
          } catch {
            setHealth(d.id, 'unreachable')
          }
        }
      }
    }

    checkAll()
    const interval = setInterval(checkAll, 30_000)
    return () => clearInterval(interval)
  // Only re-run when enabled integration IDs change
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabledDefs.map((d) => d.id).join(',')])

  if (enabledDefs.length === 0) return null

  const handleChipClick = async (integrationId: string) => {
    if (pending[integrationId]) return
    setPending((p) => ({ ...p, [integrationId]: true }))
    try {
      // Mistral Voice also kills any in-flight TTS streaming alongside the
      // plugin's own emergencyStop — clicking the chip during read-aloud
      // must cut both synthesis and already-queued audio.
      if (integrationId === MISTRAL_VOICE_ID) {
        cancelStreamingAutoRead()
        setActiveReader(null, 'idle')
      }
      const plugin = getPlugin(integrationId)
      const config = configs[integrationId]?.config ?? {}
      if (plugin?.emergencyStop) {
        try {
          await plugin.emergencyStop(config)
        } catch {
          // Best-effort stop
        }
      }
    } finally {
      setPending((p) => {
        const next = { ...p }
        delete next[integrationId]
        return next
      })
    }
  }

  return (
    <div className="flex items-center gap-2">
      {enabledDefs.map((d) => {
        const health = healthStatus[d.id] ?? 'unknown'
        const dotColour = health === 'connected' ? 'bg-green-400'
          : health === 'reachable' ? 'bg-yellow-400'
          : health === 'unreachable' ? 'bg-red-400'
          : 'bg-white/20'
        const isMistralVoice = d.id === MISTRAL_VOICE_ID
        const showPlayIndicator = isMistralVoice && audioActive
        const isPending = !!pending[d.id]

        return (
          <button
            key={d.id}
            type="button"
            onClick={() => handleChipClick(d.id)}
            disabled={isPending}
            className="flex items-center gap-1.5 px-2 py-1 rounded border border-white/10 bg-white/[0.03] text-[10px] font-mono text-white/50 hover:bg-white/[0.06] hover:text-white/70 cursor-pointer disabled:cursor-not-allowed disabled:opacity-60 transition-colors"
            title={`${d.display_name}: ${health} — click for emergency stop`}
            aria-label={`Emergency stop ${d.display_name}`}
          >
            <span className={`inline-block w-1.5 h-1.5 rounded-full ${dotColour}`} />
            {d.display_name}
            {showPlayIndicator && (
              <span
                aria-hidden="true"
                className="inline-block w-0 h-0 ml-0.5 border-y-[3px] border-y-transparent border-l-[5px] border-l-current animate-pulse"
              />
            )}
          </button>
        )
      })}
    </div>
  )
}
