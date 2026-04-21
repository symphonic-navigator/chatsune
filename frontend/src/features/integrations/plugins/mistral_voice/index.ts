import type { IntegrationPlugin, Option } from '../../types'
import { sttRegistry, ttsRegistry, declareProviderEngines } from '../../../voice/engines/registry'
import { MistralSTTEngine, MistralTTSEngine } from './engines'
import { mistralVoices, refreshMistralVoices, invalidateVoicesCache } from './voices'
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
    void refreshMistralVoices()
  },

  onDeactivate(): void {
    sttInstance = null
    ttsInstance = null
    invalidateVoicesCache()
  },

  async getPersonaConfigOptions(fieldKey: string): Promise<Option[]> {
    if (fieldKey !== 'voice_id' && fieldKey !== 'narrator_voice_id') return []
    await refreshMistralVoices()
    const voiceOptions = mistralVoices.current.map((v) => ({ value: v.id, label: v.name }))
    if (fieldKey === 'narrator_voice_id') {
      return [{ value: null, label: 'Inherit from primary voice' }, ...voiceOptions]
    }
    return voiceOptions
  },
}

registerPlugin(mistralVoicePlugin)

export default mistralVoicePlugin
