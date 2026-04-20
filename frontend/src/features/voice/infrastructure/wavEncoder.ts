/**
 * Converts a Float32Array of PCM audio (mono, `sampleRate` Hz) to a WAV Blob.
 *
 * Used exclusively as the Tier-3 fallback when MediaRecorder is not
 * available or no preferred MIME type is supported. Tier-1/2 paths stream
 * compressed audio directly from MediaRecorder and never touch this.
 */
export function float32ToWavBlob(samples: Float32Array, sampleRate = 16_000): Blob {
  const numSamples = samples.length
  const bytesPerSample = 2 // 16-bit PCM
  const dataLength = numSamples * bytesPerSample
  const buffer = new ArrayBuffer(44 + dataLength)
  const view = new DataView(buffer)

  const writeStr = (offset: number, str: string): void => {
    for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i))
  }
  const writeU32 = (offset: number, v: number): void => view.setUint32(offset, v, true)
  const writeU16 = (offset: number, v: number): void => view.setUint16(offset, v, true)

  writeStr(0, 'RIFF')
  writeU32(4, 36 + dataLength)
  writeStr(8, 'WAVE')
  writeStr(12, 'fmt ')
  writeU32(16, 16)                          // PCM chunk size
  writeU16(20, 1)                            // PCM format
  writeU16(22, 1)                            // mono
  writeU32(24, sampleRate)
  writeU32(28, sampleRate * bytesPerSample)  // byte rate
  writeU16(32, bytesPerSample)               // block align
  writeU16(34, 16)                           // bits per sample
  writeStr(36, 'data')
  writeU32(40, dataLength)

  let offset = 44
  for (let i = 0; i < numSamples; i++) {
    const clamped = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true)
    offset += 2
  }

  return new Blob([buffer], { type: 'audio/wav' })
}
