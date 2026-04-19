/**
 * Per-integration defaults shared by the read-aloud paths (manual button,
 * auto-read and conversational mode) so the same fallback applies wherever
 * `playback_gap_ms` is read.
 *
 * Mistral TTS has sharp sentence edges so a small gap sounds more natural
 * (default 500 ms). xAI already leaves a natural silence at sentence
 * boundaries, so 0 ms is the right default.
 */
const DEFAULT_GAP_BY_INTEGRATION: Record<string, number> = {
  mistral_voice: 500,
  xai_voice: 0,
}

const FALLBACK_GAP_MS = 500

export function resolveGapMs(
  integrationId: string | undefined,
  integrationCfg: Record<string, unknown> | undefined,
): number {
  const raw = integrationCfg?.playback_gap_ms
  if (typeof raw === 'string') {
    const n = Number.parseInt(raw, 10)
    if (Number.isFinite(n) && n >= 0) return n
  }
  if (typeof raw === 'number' && Number.isFinite(raw) && raw >= 0) return raw
  if (integrationId && integrationId in DEFAULT_GAP_BY_INTEGRATION) {
    return DEFAULT_GAP_BY_INTEGRATION[integrationId]
  }
  return FALLBACK_GAP_MS
}
