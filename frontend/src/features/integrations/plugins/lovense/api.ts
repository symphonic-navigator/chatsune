function buildUrl(ip: string): string {
  const dashed = ip.trim().replace(/\./g, '-')
  return `https://${dashed}.lovense.club:30010/command`
}

export async function sendCommand(ip: string, body: Record<string, unknown>): Promise<Record<string, unknown>> {
  const url = buildUrl(ip)
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return await res.json()
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

export async function vibrate(ip: string, toy: string, strength: number, seconds: number): Promise<Record<string, unknown>> {
  return sendCommand(ip, {
    command: 'Function',
    action: `Vibrate:${strength}`,
    timeSec: seconds,
    toy,
  })
}

export async function rotate(ip: string, toy: string, strength: number, seconds: number): Promise<Record<string, unknown>> {
  return sendCommand(ip, {
    command: 'Function',
    action: `Rotate:${strength}`,
    timeSec: seconds,
    toy,
  })
}

export async function stopToy(ip: string, toy: string): Promise<Record<string, unknown>> {
  return sendCommand(ip, { command: 'Function', action: 'Stop', toy })
}

export async function stopAll(ip: string): Promise<Record<string, unknown>> {
  return sendCommand(ip, { command: 'Function', action: 'Stop' })
}
