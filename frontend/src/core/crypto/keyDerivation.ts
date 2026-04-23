import type { Argon2Request, Argon2Response } from './argon2.worker'

export interface KdfParams {
  memoryKib: number
  iterations: number
  parallelism: number
}

export interface DerivedHashes {
  hAuth: Uint8Array  // 32 bytes
  hKek: Uint8Array   // 32 bytes
}

let workerSingleton: Worker | null = null

function getWorker(): Worker {
  if (!workerSingleton) {
    workerSingleton = new Worker(new URL('./argon2.worker.ts', import.meta.url), { type: 'module' })
  }
  return workerSingleton
}

async function runArgon2id(password: string, salt: Uint8Array, params: KdfParams): Promise<Uint8Array> {
  const worker = getWorker()
  return new Promise((resolve, reject) => {
    const handler = (e: MessageEvent<Argon2Response | { error: string }>) => {
      worker.removeEventListener('message', handler)
      if ('error' in e.data) reject(new Error(e.data.error))
      else resolve(e.data.hash)
    }
    worker.addEventListener('message', handler)
    const req: Argon2Request = { password, salt, ...params }
    worker.postMessage(req)
  })
}

async function hkdfSha256(ikm: Uint8Array, info: string, length: number): Promise<Uint8Array> {
  // Copy into a fresh ArrayBuffer-backed Uint8Array to satisfy BufferSource expectations.
  const ikmCopy = new Uint8Array(ikm.length)
  ikmCopy.set(ikm)
  const infoBytes = new TextEncoder().encode(info)
  const baseKey = await crypto.subtle.importKey('raw', ikmCopy.buffer as ArrayBuffer, 'HKDF', false, ['deriveBits'])
  const derived = await crypto.subtle.deriveBits(
    { name: 'HKDF', hash: 'SHA-256', salt: new Uint8Array(0), info: infoBytes },
    baseKey,
    length * 8,
  )
  return new Uint8Array(derived)
}

/**
 * Runs Argon2id on the password (in a Web Worker so the UI stays responsive),
 * then splits the 64-byte output into two purpose-scoped 32-byte keys via HKDF.
 * `hAuth` is sent to the server for bcrypt verification; `hKek` unlocks the DEK.
 * Corresponding server-side HKDF-info strings are "chatsune-auth" and "chatsune-kek".
 */
export async function deriveAuthAndKek(password: string, salt: Uint8Array, params: KdfParams): Promise<DerivedHashes> {
  const h = await runArgon2id(password, salt, params)
  const [hAuth, hKek] = await Promise.all([
    hkdfSha256(h, 'chatsune-auth', 32),
    hkdfSha256(h, 'chatsune-kek', 32),
  ])
  return { hAuth, hKek }
}

export function toBase64Url(bytes: Uint8Array): string {
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  const b64 = btoa(binary)
  return b64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

export function fromBase64Url(s: string): Uint8Array {
  let normalised = s.replace(/-/g, '+').replace(/_/g, '/')
  while (normalised.length % 4) normalised += '='
  const bin = atob(normalised)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}
