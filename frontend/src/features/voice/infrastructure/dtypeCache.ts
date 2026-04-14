import { CACHE_VERSION } from './capabilityProbe'

const DB_NAME = 'chatsune-voice-meta'
const STORE = 'dtypeDecisions'
const DB_VERSION = 1

export interface Decision {
  device: 'webgpu' | 'wasm'
  dtype: string
  decidedAt: string
  cacheVersion: number
}

// Cached connection — closed and nulled by _resetForTests.
let _db: IDBDatabase | null = null

function openDb(): Promise<IDBDatabase> {
  if (_db) return Promise.resolve(_db)
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE)
      }
    }
    req.onsuccess = () => {
      _db = req.result
      resolve(_db)
    }
    req.onerror = () => reject(req.error)
  })
}

function key(modelId: string, fingerprint: string): string {
  return `${modelId}:${fingerprint}`
}

export async function getDecision(
  modelId: string,
  fingerprint: string,
): Promise<Decision | null> {
  const db = await openDb()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readonly')
    const req = tx.objectStore(STORE).get(key(modelId, fingerprint))
    req.onsuccess = () => {
      const v = req.result as Decision | undefined
      if (!v) return resolve(null)
      if (v.cacheVersion !== CACHE_VERSION) return resolve(null)
      resolve(v)
    }
    req.onerror = () => reject(req.error)
  })
}

export async function putDecision(
  modelId: string,
  fingerprint: string,
  choice: { device: 'webgpu' | 'wasm'; dtype: string },
): Promise<void> {
  const db = await openDb()
  const record: Decision = {
    ...choice,
    decidedAt: new Date().toISOString(),
    cacheVersion: CACHE_VERSION,
  }
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite')
    tx.objectStore(STORE).put(record, key(modelId, fingerprint))
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error)
  })
}

// Test-only: close open connection then wipe the DB so each test starts clean.
export async function _resetForTests(): Promise<void> {
  if (_db) {
    _db.close()
    _db = null
  }
  await new Promise<void>((resolve, reject) => {
    const req = indexedDB.deleteDatabase(DB_NAME)
    req.onsuccess = () => resolve()
    req.onerror = () => reject(req.error)
    req.onblocked = () => resolve()
  })
}
