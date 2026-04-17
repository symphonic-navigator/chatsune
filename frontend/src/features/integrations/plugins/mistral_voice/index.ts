import type { IntegrationPlugin, Option } from '../../types'
import { sttRegistry, ttsRegistry } from '../../../voice/engines/registry'
import { MistralSTTEngine, MistralTTSEngine } from './engines'
import { mistralVoices } from './voices'
import { registerPlugin } from '../../registry'

let sttInstance: MistralSTTEngine | null = null
let ttsInstance: MistralTTSEngine | null = null

const mistralVoicePlugin: IntegrationPlugin = {
  id: 'mistral_voice',

  onActivate(): void {
    if (!sttInstance) sttInstance = new MistralSTTEngine()
    if (!ttsInstance) ttsInstance = new MistralTTSEngine()
    sttRegistry.register(sttInstance)
    ttsRegistry.register(ttsInstance)
  },

  onDeactivate(): void {
    // EngineRegistry has no unregister method — engines remain listed but
    // the caller is expected to setActive to a different engine. Nothing to do here.
    sttInstance = null
    ttsInstance = null
  },

  async getPersonaConfigOptions(fieldKey: string): Promise<Option[]> {
    if (fieldKey !== 'voice_id') return []
    return mistralVoices.current.map((v) => ({ value: v.id, label: v.name }))
  },
}

registerPlugin(mistralVoicePlugin)

export default mistralVoicePlugin
