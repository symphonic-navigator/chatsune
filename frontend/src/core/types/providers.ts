export const Capability = {
  LLM: 'llm',
  TTS: 'tts',
  STT: 'stt',
  WEBSEARCH: 'websearch',
  TTI: 'tti',
  ITI: 'iti',
} as const
export type Capability = (typeof Capability)[keyof typeof Capability]

export interface CapabilityMeta {
  label: string
  tooltip: string
}

export const CAPABILITY_META: Record<Capability, CapabilityMeta> = {
  llm:       { label: 'Text',          tooltip: 'Provides chat models you can pick for any persona.' },
  tts:       { label: 'TTS',           tooltip: 'Synthesises persona replies into speech for voice chats.' },
  stt:       { label: 'STT',           tooltip: 'Transcribes your voice input into text for the chat.' },
  websearch: { label: 'Web search',    tooltip: 'Provides web search during chats, regardless of which model you use.' },
  tti:       { label: 'Text to Image', tooltip: 'Creates images from a text prompt during chats.' },
  iti:       { label: 'Image to Image', tooltip: 'Edits or transforms an uploaded image based on a prompt.' },
}

export interface PremiumProviderDefinition {
  id: string
  display_name: string
  icon: string
  base_url: string
  capabilities: Capability[]
  config_fields: Array<Record<string, unknown>>
  linked_integrations: string[]
}

export interface PremiumProviderAccount {
  provider_id: string
  config: Record<string, unknown>
  last_test_status: 'ok' | 'error' | null
  last_test_error: string | null
  last_test_at: string | null
}
