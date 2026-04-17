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
    console.log('[mistral] getPersonaConfigOptions called with fieldKey=', fieldKey)
    if (fieldKey !== 'voice_id') return []
    const apiKey = useSecretsStore.getState().getSecret('mistral_voice', 'api_key')
    console.log('[mistral] apiKey present?', !!apiKey, 'mistralVoices.current.length BEFORE refresh:', mistralVoices.current.length)
    if (apiKey) {
      try {
        await refreshMistralVoices(apiKey)
        console.log('[mistral] after refresh, voices count:', mistralVoices.current.length, 'sample:', mistralVoices.current.slice(0, 3))
      } catch (err) {
        console.error('[mistral] refreshMistralVoices threw:', err)
      }
    }
    const options = mistralVoices.current.map((v) => ({ value: v.id, label: v.name }))
    console.log('[mistral] returning options count:', options.length)
    return options
  },
}

registerPlugin(mistralVoicePlugin)

export default mistralVoicePlugin
