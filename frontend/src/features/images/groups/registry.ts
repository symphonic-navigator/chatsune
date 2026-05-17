import type { ImageGroupConfig } from '@/core/api/images'
import type { ComponentType } from 'react'
import { XaiImagineConfigView } from './XaiImagineConfigView'
import { ZImageConfigView } from './ZImageConfigView'
import { SeedreamConfigView } from './SeedreamConfigView'

export type ConfigViewProps<T extends ImageGroupConfig> = {
  config: T
  onChange: (next: T) => void
}

export type ConfigViewComponent = ComponentType<ConfigViewProps<ImageGroupConfig>>

/**
 * Map of group_id → config-view component.
 *
 * Keys are group_ids ("xai_imagine", "nano_gpt_zimage", "nano_gpt_seedream").
 * The cast to ConfigViewComponent is safe: the panel only renders the view
 * whose group_id matches, so the discriminated union is enforced at runtime.
 */
export const IMAGE_GROUP_VIEWS: Partial<Record<string, ConfigViewComponent>> = {
  xai_imagine: XaiImagineConfigView as ConfigViewComponent,
  nano_gpt_zimage: ZImageConfigView as ConfigViewComponent,
  nano_gpt_seedream: SeedreamConfigView as ConfigViewComponent,
}
