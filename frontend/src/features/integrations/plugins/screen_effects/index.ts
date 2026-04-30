import type { IntegrationPlugin } from '../../types'
import { registerPlugin } from '../../registry'
import { executeTag } from './tags'

const screenEffectsPlugin: IntegrationPlugin = {
  id: 'screen_effect',
  executeTag,
}

registerPlugin(screenEffectsPlugin)

export default screenEffectsPlugin
