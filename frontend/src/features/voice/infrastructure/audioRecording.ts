// Mime-type discovery + recorder factory for the parallel MediaRecorder
// pipeline. Keeps the three-tier fallback (webm/opus → mp4/aac → WAV) in
// one place so audioCapture.ts and useConversationMode can share it.
//
// Tier 1: audio/webm;codecs=opus  — Chrome, Firefox, desktop Edge.
//         ~9.7 KB per 3 s of speech (~10x smaller than WAV).
// Tier 2: audio/mp4               — Safari (macOS + iOS).
//         ~19 KB per 3 s (~5x smaller than WAV).
// Tier 3: audio/wav (no MediaRecorder) — legacy / unknown browsers.
//         Falls through to float32ToWavBlob at the call site.

/**
 * Preferred MIME types in priority order. The first one supported by the
 * current browser's MediaRecorder wins.
 *
 * Order rationale:
 *  - `audio/webm;codecs=opus` is explicit about Opus; Chrome/Firefox honour it.
 *  - `audio/webm` without codec hint covers the rare Chromium build that
 *    ships webm but not the codec probe.
 *  - `audio/mp4` and `audio/mp4;codecs=mp4a.40.2` cover Safari. The more
 *    specific string comes last so we prefer the generic probe first; Safari
 *    accepts both.
 */
const PREFERRED_MIME_TYPES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/mp4',
  'audio/mp4;codecs=mp4a.40.2',
] as const

/**
 * Returns the first MIME type from {@link PREFERRED_MIME_TYPES} that this
 * browser's MediaRecorder supports, or `null` if MediaRecorder is unavailable
 * or none of the preferred types are supported.
 *
 * `null` is the signal for callers to fall through to the Tier-3 WAV path.
 */
export function pickRecordingMimeType(): string | null {
  const Recorder: typeof MediaRecorder | undefined =
    (globalThis as { MediaRecorder?: typeof MediaRecorder }).MediaRecorder
  if (typeof Recorder === 'undefined') return null
  if (typeof Recorder.isTypeSupported !== 'function') return null
  for (const mime of PREFERRED_MIME_TYPES) {
    try {
      if (Recorder.isTypeSupported(mime)) return mime
    } catch {
      // Some older browsers throw on unknown MIME strings instead of
      // returning false. Treat that as "not supported" and continue.
    }
  }
  return null
}

/**
 * Map a recording MIME type to the file extension servers expect. Some
 * multipart backends use the filename as a disambiguator when the
 * Content-Type is generic; keeping the extension aligned avoids that trap.
 */
export function extensionForMimeType(mimeType: string): string {
  if (mimeType.startsWith('audio/webm')) return 'webm'
  if (mimeType.startsWith('audio/mp4')) return 'm4a'
  if (mimeType === 'audio/wav') return 'wav'
  return 'bin'
}

/**
 * Construct a MediaRecorder with sensible bitrates for the chosen codec.
 *
 * 24 kbit/s is the Opus sweet spot for speech — intelligible and ~10x
 * smaller than WAV. AAC needs more bits for the same perceived quality
 * (Safari's encoder is less efficient at low bitrates), so we budget 48
 * kbit/s there.
 */
export function createRecorder(stream: MediaStream, mimeType: string): MediaRecorder {
  const bitrate = mimeType.startsWith('audio/webm') ? 24_000 : 48_000
  return new MediaRecorder(stream, { mimeType, audioBitsPerSecond: bitrate })
}
