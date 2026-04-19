import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { PersonaDto } from '../../../../core/types/persona'

// Mock the integrations store so we control which integrations are "enabled"
vi.mock('../../../integrations/store', () => ({
  useIntegrationsStore: {
    getState: vi.fn(() => ({
      definitions: [
        { id: 'mistral_voice', capabilities: ['tts_provider', 'stt_provider'] },
        { id: 'xai_voice', capabilities: ['tts_provider', 'stt_provider'] },
      ],
      configs: {
        mistral_voice: { enabled: true },
        xai_voice: { enabled: true },
      },
    })),
  },
}))

// Stub the registry lookups so tests don't need real engines
vi.mock('../registry', async () => {
  const actual = await vi.importActual<typeof import('../registry')>('../registry')
  return {
    ...actual,
    sttRegistry: {
      get: (id: string) => ({ id, name: id, isReady: () => true }) as any,
      list: () => ([
        { id: 'mistral_stt', isReady: () => true },
        { id: 'xai_stt', isReady: () => true },
      ]) as any,
    },
    ttsRegistry: {
      get: (id: string) => ({ id, name: id, isReady: () => true }) as any,
      list: () => ([
        { id: 'mistral_tts', isReady: () => true },
        { id: 'xai_tts', isReady: () => true },
      ]) as any,
    },
    providerToEngineId: (iid: string, kind: 'stt' | 'tts') => {
      if (iid === 'mistral_voice') return kind === 'stt' ? 'mistral_stt' : 'mistral_tts'
      if (iid === 'xai_voice') return kind === 'stt' ? 'xai_stt' : 'xai_tts'
      return undefined
    },
  }
})

import { resolveTTSEngine, resolveSTTEngine } from '../resolver'
import { useVoiceSettingsStore } from '../../stores/voiceSettingsStore'

function persona(overrides: Partial<PersonaDto> = {}): PersonaDto {
  return {
    id: 'p1',
    voice_config: {},
    ...overrides,
  } as PersonaDto
}

describe('resolveTTSEngine', () => {
  it('uses tts_provider_id when set and engine is ready', () => {
    const p = persona({ voice_config: { tts_provider_id: 'xai_voice' } as any })
    const engine = resolveTTSEngine(p)
    expect(engine?.id).toBe('xai_tts')
  })

  it('falls back to first enabled TTS provider when tts_provider_id is unset', () => {
    const p = persona()
    const engine = resolveTTSEngine(p)
    expect(engine?.id).toBe('mistral_tts')
  })
})

describe('resolveSTTEngine', () => {
  beforeEach(() => {
    useVoiceSettingsStore.setState({ stt_provider_id: undefined } as Partial<
      ReturnType<typeof useVoiceSettingsStore.getState>
    >)
  })

  it('uses stt_provider_id from voice settings when set', () => {
    useVoiceSettingsStore.setState({ stt_provider_id: 'xai_voice' } as Partial<
      ReturnType<typeof useVoiceSettingsStore.getState>
    >)
    const engine = resolveSTTEngine()
    expect(engine?.id).toBe('xai_stt')
  })

  it('falls back to first enabled STT provider when unset', () => {
    const engine = resolveSTTEngine()
    expect(engine?.id).toBe('mistral_stt')
  })
})
