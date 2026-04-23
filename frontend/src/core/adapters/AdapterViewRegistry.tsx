import type { ComponentType } from 'react'
import type { Connection } from '../types/llm'
import { OllamaHttpView } from '../../app/components/llm-providers/adapter-views/OllamaHttpView'
import { CommunityView } from '../../app/components/llm-providers/adapter-views/CommunityView'
import { XaiHttpView } from '../../app/components/llm-providers/adapter-views/XaiHttpView'

export interface AdapterViewProps {
  connection: Connection
  /**
   * Names of config fields that must be non-empty for the save to proceed.
   * Sourced from the template selected in the wizard. Empty in edit mode —
   * existing connections may legitimately pre-date a field becoming required.
   */
  requiredConfigFields: string[]
  onConfigChange: (config: Record<string, unknown>) => void
  onDisplayNameChange: (name: string) => void
  onSlugChange: (slug: string) => void
}

export const ADAPTER_VIEW_REGISTRY: Record<string, ComponentType<AdapterViewProps>> = {
  ollama_http: OllamaHttpView,
  community: CommunityView,
  xai_http: XaiHttpView,
}

export function resolveAdapterView(viewId: string): ComponentType<AdapterViewProps> | null {
  return ADAPTER_VIEW_REGISTRY[viewId] ?? null
}
