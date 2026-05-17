import type { IntegrationPlugin, Option } from '../../types'
import {
  sttRegistry,
  ttsRegistry,
  declareProviderEngines,
} from '../../../voice/engines/registry'
import { NanoGptXaiSTTEngine, NanoGptXaiTTSEngine } from './engines'
import {
  nanoGptXaiVoices,
  refreshNanoGptXaiVoices,
  invalidateNanoGptXaiVoicesCache,
} from './voices'
import { registerPlugin } from '../../registry'

declareProviderEngines('nano_gpt_voice_xai', {
  stt: 'nano_gpt_voice_xai_stt',
  tts: 'nano_gpt_voice_xai_tts',
})

let sttInstance: NanoGptXaiSTTEngine | null = null
let ttsInstance: NanoGptXaiTTSEngine | null = null

const nanoGptVoiceXaiPlugin: IntegrationPlugin = {
  id: 'nano_gpt_voice_xai',

  onActivate(): void {
    if (!sttInstance) sttInstance = new NanoGptXaiSTTEngine()
    if (!ttsInstance) ttsInstance = new NanoGptXaiTTSEngine()
    sttRegistry.register(sttInstance)
    ttsRegistry.register(ttsInstance)
    void refreshNanoGptXaiVoices()
  },

  onDeactivate(): void {
    sttInstance = null
    ttsInstance = null
    invalidateNanoGptXaiVoicesCache()
  },

  async getPersonaConfigOptions(fieldKey: string): Promise<Option[]> {
    if (fieldKey !== 'voice_id' && fieldKey !== 'narrator_voice_id') return []
    await refreshNanoGptXaiVoices()
    const voiceOptions = nanoGptXaiVoices.current.map(
      (v) => ({ value: v.id, label: v.name }),
    )
    if (fieldKey === 'narrator_voice_id') {
      return [
        { value: null, label: 'Inherit from primary voice' },
        ...voiceOptions,
      ]
    }
    return voiceOptions
  },
}

registerPlugin(nanoGptVoiceXaiPlugin)

export default nanoGptVoiceXaiPlugin
