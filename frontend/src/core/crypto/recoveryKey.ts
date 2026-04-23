const ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'

const DECODE: Record<string, number> = {}
for (let i = 0; i < ALPHABET.length; i++) {
  DECODE[ALPHABET[i]] = i
}
// Crockford leniency: treat visually-ambiguous characters as canonical equivalents
DECODE['O'] = DECODE['0']
DECODE['I'] = DECODE['1']
DECODE['L'] = DECODE['1']
for (const key of Object.keys(DECODE)) {
  DECODE[key.toLowerCase()] = DECODE[key]
}

export const RECOVERY_KEY_RAW_BYTES = 20
export const RECOVERY_KEY_DISPLAY_LENGTH = 39   // 32 alphabet chars + 7 hyphens

export class InvalidRecoveryKeyError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'InvalidRecoveryKeyError'
  }
}

/** Generate a fresh 160-bit recovery key in display form. */
export function generateRecoveryKey(): string {
  const raw = new Uint8Array(RECOVERY_KEY_RAW_BYTES)
  crypto.getRandomValues(raw)
  return encodeRecoveryKey(raw)
}

/** Encode 20 raw bytes as `XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX` (39 chars). */
export function encodeRecoveryKey(raw: Uint8Array): string {
  if (raw.length !== RECOVERY_KEY_RAW_BYTES) {
    throw new InvalidRecoveryKeyError(`raw must be ${RECOVERY_KEY_RAW_BYTES} bytes, got ${raw.length}`)
  }
  // Big-endian int, then repeatedly divmod 32.
  let n = 0n
  for (const b of raw) n = (n << 8n) | BigInt(b)
  const chars: string[] = []
  for (let i = 0; i < 32; i++) {
    chars.push(ALPHABET[Number(n & 31n)])
    n >>= 5n
  }
  const compact = chars.reverse().join('')
  return [
    compact.slice(0, 4), compact.slice(4, 8), compact.slice(8, 12), compact.slice(12, 16),
    compact.slice(16, 20), compact.slice(20, 24), compact.slice(24, 28), compact.slice(28, 32),
  ].join('-')
}

/** Strip whitespace + hyphens, uppercase. Result is 32 significant chars on success. */
export function normaliseRecoveryKey(input: string): string {
  return input.replace(/[\s-]/g, '').toUpperCase()
}

/** Decode a display-form or compact-form recovery key to its 20 raw bytes. */
export function decodeRecoveryKey(input: string): Uint8Array {
  const s = normaliseRecoveryKey(input)
  if (s.length !== 32) {
    throw new InvalidRecoveryKeyError(`must have 32 significant characters, got ${s.length}`)
  }
  let n = 0n
  for (const ch of s) {
    const v = DECODE[ch]
    if (v === undefined) throw new InvalidRecoveryKeyError(`invalid character: ${ch}`)
    n = n * 32n + BigInt(v)
  }
  const out = new Uint8Array(RECOVERY_KEY_RAW_BYTES)
  for (let i = RECOVERY_KEY_RAW_BYTES - 1; i >= 0; i--) {
    out[i] = Number(n & 0xffn)
    n >>= 8n
  }
  return out
}
