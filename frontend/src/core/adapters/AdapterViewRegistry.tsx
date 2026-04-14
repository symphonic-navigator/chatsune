import type { ComponentType } from 'react'
import type { Connection } from '../types/llm'
import { OllamaHttpView } from '../../app/components/llm-providers/adapter-views/OllamaHttpView'

export interface AdapterViewProps {
  connection: Connection
  onConfigChange: (config: Record<string, unknown>) => void
  onDisplayNameChange: (name: string) => void
  onSlugChange: (slug: string) => void
}

export const ADAPTER_VIEW_REGISTRY: Record<string, ComponentType<AdapterViewProps>> = {
  ollama_http: OllamaHttpView,
}

export function resolveAdapterView(viewId: string): ComponentType<AdapterViewProps> | null {
  return ADAPTER_VIEW_REGISTRY[viewId] ?? null
}
