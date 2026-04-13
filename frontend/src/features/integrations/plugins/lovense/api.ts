function buildUrl(ip: string): string {
  const dashed = ip.trim().replace(/\./g, '-')
  return `https://${dashed}.lovense.club:30010/command`
}

export async function sendCommand(ip: string, body: Record<string, unknown>): Promise<Record<string, unknown>> {
  const url = buildUrl(ip)
  console.debug('[lovense] POST %s %o', url, body)
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const json = await res.json()
  console.debug('[lovense] response status=%d %o', res.status, json)
  if (!res.ok) {
    console.warn('[lovense] HTTP %d for %s', res.status, url)
  }
  return json
}

export interface ToyInfo {
  id: string
  name: string
  nickName: string
  status: 'online' | 'offline'
  battery: number
  capabilities: string[]
}

export interface GetToysResult {
  ok: boolean
  toys: ToyInfo[]
  platform: string
  raw: Record<string, unknown>
}

export async function getToys(ip: string): Promise<Record<string, unknown>> {
  return sendCommand(ip, { command: 'GetToys' })
}

/** Parse the GetToys response into a clean structure. */
export function parseGetToysResponse(raw: Record<string, unknown>): GetToysResult {
  const code = raw.code as number | undefined
  const data = raw.data as Record<string, unknown> | undefined

  if (code !== 200 || !data) {
    return { ok: false, toys: [], platform: '', raw }
  }

  const platform = (data.platform as string) ?? ''
  const toysStr = data.toys as string | undefined
  if (!toysStr) {
    return { ok: true, toys: [], platform, raw }
  }

  let toysMap: Record<string, Record<string, unknown>>
  try {
    toysMap = JSON.parse(toysStr)
  } catch {
    return { ok: true, toys: [], platform, raw }
  }

  const toys: ToyInfo[] = Object.values(toysMap).map((t) => ({
    id: (t.id as string) ?? '',
    name: (t.name as string) ?? '',
    nickName: (t.nickName as string) ?? '',
    status: String(t.status) === '1' ? 'online' : 'offline',
    battery: (t.battery as number) ?? 0,
    capabilities: (t.fullFunctionNames as string[]) ?? [],
  }))

  return { ok: true, toys, platform, raw }
}

// ---------------------------------------------------------------------------
// Toy name → ID cache (the Lovense API expects IDs, the LLM uses names)
// ---------------------------------------------------------------------------

const CACHE_TTL_MS = 15_000

interface ToyCache {
  /** name (lowercase) → id */
  nameToId: Map<string, string>
  /** nickName (lowercase) → id */
  nickToId: Map<string, string>
  fetchedAt: number
  ip: string
}

let _toyCache: ToyCache | null = null

function cacheIsValid(ip: string): boolean {
  return _toyCache !== null
    && _toyCache.ip === ip
    && Date.now() - _toyCache.fetchedAt < CACHE_TTL_MS
}

async function ensureCache(ip: string): Promise<ToyCache> {
  if (cacheIsValid(ip)) return _toyCache!

  console.debug('[lovense] refreshing toy cache for ip=%s', ip)
  const raw = await getToys(ip)
  const parsed = parseGetToysResponse(raw)

  const nameToId = new Map<string, string>()
  const nickToId = new Map<string, string>()
  for (const t of parsed.toys) {
    if (t.name) nameToId.set(t.name.toLowerCase(), t.id)
    if (t.nickName) nickToId.set(t.nickName.toLowerCase(), t.id)
  }

  _toyCache = { nameToId, nickToId, fetchedAt: Date.now(), ip }
  console.debug('[lovense] cache populated: %d toys', parsed.toys.length)
  return _toyCache
}

/**
 * Resolve a toy name/nick to its hardware ID.
 * Falls back to the input unchanged if no match (might already be an ID).
 */
export async function resolveToyId(ip: string, nameOrNick: string): Promise<string> {
  const cache = await ensureCache(ip)
  const lower = nameOrNick.toLowerCase()
  const byName = cache.nameToId.get(lower)
  if (byName) return byName
  const byNick = cache.nickToId.get(lower)
  if (byNick) return byNick
  // Might already be an ID — pass through
  console.debug('[lovense] no cache hit for "%s", passing through as-is', nameOrNick)
  return nameOrNick
}

/** Invalidate the cache (e.g. after emergency stop). */
export function invalidateToyCache(): void {
  _toyCache = null
}

/** All actions supported by the Lovense Function API. */
export const ACTIONS = [
  'Vibrate', 'Rotate', 'Pump', 'Thrusting', 'Fingering',
  'Suction', 'Depth', 'Oscillate', 'All',
] as const
export type Action = (typeof ACTIONS)[number]

/** Max strength per action — most are 0-20, some are 0-3. */
export function maxStrength(action: Action | 'Stroke'): number {
  if (action === 'Pump' || action === 'Depth') return 3
  if (action === 'Stroke') return 100
  return 20
}

export interface FunctionParams {
  action: Action | 'Stop'
  strength?: number
  timeSec?: number
  toy?: string
  loopRunningSec?: number
  loopPauseSec?: number
  stopPrevious?: boolean
}

/** Send a Function command to the Lovense API. Resolves toy names to IDs automatically. */
export async function functionCommand(ip: string, params: FunctionParams): Promise<Record<string, unknown>> {
  const actionStr = params.action === 'Stop'
    ? 'Stop'
    : `${params.action}:${params.strength ?? 0}`

  // Resolve toy name → ID
  const toyId = params.toy ? await resolveToyId(ip, params.toy) : undefined

  const body: Record<string, unknown> = {
    command: 'Function',
    action: actionStr,
    timeSec: params.timeSec ?? 0,
    apiVer: 1,
  }
  if (toyId) body.toy = toyId
  if (params.loopRunningSec != null && params.loopRunningSec > 1) body.loopRunningSec = params.loopRunningSec
  if (params.loopPauseSec != null && params.loopPauseSec > 1) body.loopPauseSec = params.loopPauseSec
  if (params.stopPrevious === false) body.stopPrevious = 0

  return sendCommand(ip, body)
}

/**
 * Send a Stroke command — sets both Thrusting and Stroke actions.
 * The Lovense API requires a minimum 20-point gap between them.
 */
export async function strokeCommand(
  ip: string,
  strokePosition: number,
  thrustStrength: number,
  timeSec: number,
  toy?: string,
  stopPrevious?: boolean,
): Promise<Record<string, unknown>> {
  // Enforce the 20-point gap requirement
  const clampedStroke = Math.max(0, Math.min(100, strokePosition))
  const clampedThrust = Math.max(0, Math.min(20, thrustStrength))
  if (Math.abs(clampedStroke - clampedThrust) < 20) {
    return { code: 400, type: 'ERROR', message: 'Stroke and Thrusting must differ by at least 20 points' }
  }

  // Resolve toy name once for both calls
  const toyId = toy ? await resolveToyId(ip, toy) : undefined

  // Send thrusting first, then stroke with stopPrevious=0 to layer
  await functionCommand(ip, {
    action: 'Thrusting',
    strength: clampedThrust,
    timeSec,
    toy: toyId,
    stopPrevious,
  })
  return functionCommand(ip, {
    action: 'Thrusting' as Action, // Stroke piggybacks on thrusting
    strength: clampedStroke,
    timeSec,
    toy: toyId,
    stopPrevious: false, // layer on top
  })
}

export async function stopToy(ip: string, toy: string): Promise<Record<string, unknown>> {
  return functionCommand(ip, { action: 'Stop', toy })
}

export async function stopAll(ip: string): Promise<Record<string, unknown>> {
  return functionCommand(ip, { action: 'Stop' })
}
