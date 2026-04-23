/// <reference lib="webworker" />

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
    // Dynamically import argon2-browser to avoid bundling wasm at build time
    // eslint-disable-next-line import/no-extraneous-dependencies
    const argon2Module = await (globalThis as any).importArgon2?.() ?? import(/* @vite-ignore */ 'argon2-browser')
    const argon2 = argon2Module.default || argon2Module
    const result = await argon2.hash({
      pass: password,
      salt: salt,
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
