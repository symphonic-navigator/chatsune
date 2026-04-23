declare module 'argon2-browser' {
  export enum ArgonType {
    Argon2d = 0,
    Argon2i = 1,
    Argon2id = 2,
  }

  export interface HashOptions {
    pass: string | Uint8Array
    salt: string | Uint8Array
    type?: ArgonType
    mem?: number
    time?: number
    parallelism?: number
    hashLen?: number
    secret?: Uint8Array
    ad?: Uint8Array
  }

  export interface HashResult {
    hash: Uint8Array
    hashHex: string
    encoded: string
  }

  interface Argon2Static {
    hash(options: HashOptions): Promise<HashResult>
    ArgonType: typeof ArgonType
  }

  const argon2: Argon2Static
  export default argon2
}
