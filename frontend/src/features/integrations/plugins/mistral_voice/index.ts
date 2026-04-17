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
    // If the active engine belongs to this plugin, clear it so active()
    // doesn't return a stale/disposed instance after deactivation.
    if (sttInstance && sttRegistry.active()?.id === sttInstance.id) {
      sttRegistry.clearActive()
    }
    if (ttsInstance && ttsRegistry.active()?.id === ttsInstance.id) {
      ttsRegistry.clearActive()
    }
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
