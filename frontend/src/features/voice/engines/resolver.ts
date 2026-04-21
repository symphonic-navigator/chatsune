import type { PersonaDto } from '../../../core/types/persona'
import type { STTEngine, TTSEngine } from '../types'
import { sttRegistry, ttsRegistry, providerToEngineId } from './registry'
import { useIntegrationsStore } from '../../integrations/store'
import { useVoiceSettingsStore } from '../stores/voiceSettingsStore'

// Capability string values as declared in IntegrationDefinition.capabilities.
// These are the lowercase `.value` of the IntegrationCapability enum
// (shared/dtos/integrations.py), which is what ends up in the DTO sent to
// the frontend.
const TTS_CAP = 'tts_provider'
const STT_CAP = 'stt_provider'

function firstEnabledIntegrationId(cap: string): string | undefined {
  const s = useIntegrationsStore.getState()
  const defn = s.definitions.find(
    (d: { id: string; capabilities?: string[] }) =>
      d.capabilities?.includes(cap) && s.configs?.[d.id]?.effective_enabled,
  )
  return defn?.id
}

/**
 * Resolve the TTS integration ID for a persona.
 *
 * Priority:
 * 1. The engine mapped to the persona's `tts_provider_id` (if set and ready).
 * 2. The engine of the first enabled integration that declares TTS_PROVIDER capability.
 *
 * Returns the integration ID so callers can also look up
 * persona.integration_configs[<id>] (voice_id, narrator_voice_id,
 * modulation, etc.).
 */
export function resolveTTSIntegrationId(persona: PersonaDto | null | undefined): string | undefined {
  const requested = persona?.voice_config?.tts_provider_id ?? undefined
  if (requested) {
    const engineId = providerToEngineId(requested, 'tts')
    const engine = engineId ? ttsRegistry.get(engineId) : undefined
    if (engine?.isReady()) return requested
  }
  return firstEnabledIntegrationId(TTS_CAP)
}

export function resolveTTSEngine(persona: PersonaDto | null | undefined): TTSEngine | undefined {
  const integrationId = resolveTTSIntegrationId(persona)
  if (!integrationId) return undefined
  const engineId = providerToEngineId(integrationId, 'tts')
  return engineId ? ttsRegistry.get(engineId) : undefined
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
