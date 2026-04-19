import type { PersonaDto } from '../../../core/types/persona'
import type { STTEngine, TTSEngine } from '../types'
import { sttRegistry, ttsRegistry, providerToEngineId } from './registry'
import { useIntegrationsStore } from '../../integrations/store'
import { useVoiceSettingsStore } from '../stores/voiceSettingsStore'

// Capability string values as declared in IntegrationDefinition.capabilities.
const TTS_CAP = 'TTS_PROVIDER'
const STT_CAP = 'STT_PROVIDER'

function firstEnabledIntegrationId(cap: string): string | undefined {
  const s = useIntegrationsStore.getState()
  const defn = s.definitions.find(
    (d: { id: string; capabilities?: string[] }) =>
      d.capabilities?.includes(cap) && s.configs?.[d.id]?.enabled,
  )
  return defn?.id
}

/**
 * Resolve the TTS engine for a given persona.
 *
 * Priority:
 * 1. The engine mapped to the persona's `tts_provider_id` (if set and ready).
 * 2. The engine of the first enabled integration that declares TTS_PROVIDER capability.
 *
 * `tts_provider_id` is not part of the current `PersonaDto.voice_config` shape —
 * it is stored as a loose extra key and read via a type cast.
 */
export function resolveTTSEngine(persona: PersonaDto): TTSEngine | undefined {
  const requested = (persona.voice_config as Record<string, unknown> | null | undefined)?.['tts_provider_id'] as string | undefined

  if (requested) {
    const engineId = providerToEngineId(requested, 'tts')
    const engine = engineId ? ttsRegistry.get(engineId) : undefined
    if (engine?.isReady()) return engine
    // eslint-disable-next-line no-console
    console.warn('[voice.resolver] TTS fallback: requested=%s not ready', requested)
  }

  const fallbackIntegration = firstEnabledIntegrationId(TTS_CAP)
  if (!fallbackIntegration) return undefined
  const fallbackEngineId = providerToEngineId(fallbackIntegration, 'tts')
  return fallbackEngineId ? ttsRegistry.get(fallbackEngineId) : undefined
}

/**
 * Resolve the STT engine for the current user.
 *
 * Priority:
 * 1. The engine mapped to the user's `stt_provider_id` setting (if set and ready).
 * 2. The engine of the first enabled integration that declares STT_PROVIDER capability.
 */
export function resolveSTTEngine(): STTEngine | undefined {
  const requested = useVoiceSettingsStore.getState().stt_provider_id

  if (requested) {
    const engineId = providerToEngineId(requested, 'stt')
    const engine = engineId ? sttRegistry.get(engineId) : undefined
    if (engine?.isReady()) return engine
    // eslint-disable-next-line no-console
    console.warn('[voice.resolver] STT fallback: requested=%s not ready', requested)
  }

  const fallbackIntegration = firstEnabledIntegrationId(STT_CAP)
  if (!fallbackIntegration) return undefined
  const fallbackEngineId = providerToEngineId(fallbackIntegration, 'stt')
  return fallbackEngineId ? sttRegistry.get(fallbackEngineId) : undefined
}
