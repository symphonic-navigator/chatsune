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

export async function getToys(ip: string): Promise<Record<string, unknown>> {
  return sendCommand(ip, { command: 'GetToys' })
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
