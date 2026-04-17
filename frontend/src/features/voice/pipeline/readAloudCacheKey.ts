import type { NarratorMode } from '../types'

export function readAloudCacheKey(
  messageId: string,
  primaryVoiceId: string,
  narratorVoiceId: string | null,
  mode: NarratorMode,
): string {
  return `${messageId}:${primaryVoiceId}:${narratorVoiceId ?? '-'}:${mode}`
}
