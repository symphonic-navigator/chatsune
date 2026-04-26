import type { ImageGroupConfig } from '@/core/api/images'
import type { ComponentType } from 'react'

export type ConfigViewProps<T extends ImageGroupConfig> = {
  config: T
  onChange: (next: T) => void
}

export type ConfigViewComponent = ComponentType<ConfigViewProps<ImageGroupConfig>>

/**
 * Map of group_id → config-view component.
 *
 * Filled in by Task 19 once XaiImagineConfigView exists.
 * Keys are group_ids ("xai_imagine", future: "seedream", etc.).
 */
export const IMAGE_GROUP_VIEWS: Partial<Record<string, ConfigViewComponent>> = {}
