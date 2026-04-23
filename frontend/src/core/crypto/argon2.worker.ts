/// <reference lib="webworker" />
// The bundled build embeds the wasm as base64 so vite does not need to emit a
// separate .wasm asset or chunk-split it — this avoids the wasm-loader issues
// hit with the plain `argon2-browser` import path.
import argon2 from 'argon2-browser/dist/argon2-bundled.min.js'

export interface Argon2Request {
  password: string
  salt: Uint8Array
  memoryKib: number
  iterations: number
  parallelism: number
}

export interface Argon2Response {
  hash: Uint8Array  // 64-byte H
}

self.onmessage = async (e: MessageEvent<Argon2Request>) => {
  const { password, salt, memoryKib, iterations, parallelism } = e.data
  try {
    const result = await argon2.hash({
      pass: password,
      salt,
      type: argon2.ArgonType.Argon2id,
      mem: memoryKib,
      time: iterations,
      parallelism,
      hashLen: 64,
    })
    const response: Argon2Response = { hash: new Uint8Array(result.hash) }
    ;(self as unknown as Worker).postMessage(response, [response.hash.buffer])
  } catch (err) {
    ;(self as unknown as Worker).postMessage({ error: String(err) })
  }
}
