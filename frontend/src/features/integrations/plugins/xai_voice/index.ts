import type { IntegrationPlugin, Option } from '../../types'
import { sttRegistry, ttsRegistry } from '../../../voice/engines/registry'
import { XaiSTTEngine, XaiTTSEngine } from './engines'
import { xaiVoices, refreshXaiVoices, invalidateXaiVoicesCache } from './voices'
import { registerPlugin } from '../../registry'

let sttInstance: XaiSTTEngine | null = null
let ttsInstance: XaiTTSEngine | null = null

const xaiVoicePlugin: IntegrationPlugin = {
  id: 'xai_voice',

  onActivate(): void {
    if (!sttInstance) sttInstance = new XaiSTTEngine()
    if (!ttsInstance) ttsInstance = new XaiTTSEngine()
    sttRegistry.register(sttInstance)
    ttsRegistry.register(ttsInstance)
    void refreshXaiVoices()
  },

  onDeactivate(): void {
    sttInstance = null
    ttsInstance = null
    invalidateXaiVoicesCache()
  },

  async getPersonaConfigOptions(fieldKey: string): Promise<Option[]> {
    if (fieldKey !== 'voice_id' && fieldKey !== 'narrator_voice_id') return []
    await refreshXaiVoices()
    const voiceOptions = xaiVoices.current.map((v) => ({ value: v.id, label: v.name }))
    if (fieldKey === 'narrator_voice_id') {
      return [{ value: null, label: 'Inherit from primary voice' }, ...voiceOptions]
    }
    return voiceOptions
  },
}

registerPlugin(xaiVoicePlugin)

export default xaiVoicePlugin
