import type { IntegrationPlugin, Option } from '../../types'
import { sttRegistry, ttsRegistry, declareProviderEngines } from '../../../voice/engines/registry'
import { MistralSTTEngine, MistralTTSEngine } from './engines'
import { mistralVoices, refreshMistralVoices, invalidateVoicesCache } from './voices'
import { useSecretsStore } from '../../secretsStore'
import { registerPlugin } from '../../registry'
import { ExtraConfigComponent } from './ExtraConfigComponent'

declareProviderEngines('mistral_voice', { stt: 'mistral_stt', tts: 'mistral_tts' })

let sttInstance: MistralSTTEngine | null = null
let ttsInstance: MistralTTSEngine | null = null

const mistralVoicePlugin: IntegrationPlugin = {
  id: 'mistral_voice',
  ExtraConfigComponent,

  onActivate(): void {
    if (!sttInstance) sttInstance = new MistralSTTEngine()
    if (!ttsInstance) ttsInstance = new MistralTTSEngine()
    sttRegistry.register(sttInstance)
    ttsRegistry.register(ttsInstance)
    const key = useSecretsStore.getState().getSecret('mistral_voice', 'api_key')
    if (key) void refreshMistralVoices(key)
  },

  onDeactivate(): void {
    sttInstance = null
    ttsInstance = null
    invalidateVoicesCache()
  },

  async getPersonaConfigOptions(fieldKey: string): Promise<Option[]> {
    if (fieldKey !== 'voice_id' && fieldKey !== 'narrator_voice_id') return []
    const apiKey = useSecretsStore.getState().getSecret('mistral_voice', 'api_key')
    if (apiKey) {
      await refreshMistralVoices(apiKey)
    }
    const voiceOptions = mistralVoices.current.map((v) => ({ value: v.id, label: v.name }))
    if (fieldKey === 'narrator_voice_id') {
      return [{ value: null, label: 'Inherit from primary voice' }, ...voiceOptions]
    }
    return voiceOptions
  },
}

registerPlugin(mistralVoicePlugin)

export default mistralVoicePlugin
