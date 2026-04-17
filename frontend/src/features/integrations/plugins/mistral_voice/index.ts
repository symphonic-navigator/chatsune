import type { IntegrationPlugin, Option } from '../../types'
import { sttRegistry, ttsRegistry } from '../../../voice/engines/registry'
import { MistralSTTEngine, MistralTTSEngine } from './engines'
import { mistralVoices, refreshMistralVoices } from './voices'
import { useSecretsStore } from '../../secretsStore'
import { registerPlugin } from '../../registry'
import { ExtraConfigComponent } from './ExtraConfigComponent'

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
    // EngineRegistry has no unregister method — engines remain listed but
    // the caller is expected to setActive to a different engine. Nothing to do here.
    sttInstance = null
    ttsInstance = null
  },

  async getPersonaConfigOptions(fieldKey: string): Promise<Option[]> {
    if (fieldKey !== 'voice_id') return []
    const apiKey = useSecretsStore.getState().getSecret('mistral_voice', 'api_key')
    if (apiKey && mistralVoices.current.length === 0) {
      await refreshMistralVoices(apiKey)
    }
    return mistralVoices.current.map((v) => ({ value: v.id, label: v.name }))
  },
}

registerPlugin(mistralVoicePlugin)

export default mistralVoicePlugin
