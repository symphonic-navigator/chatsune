// Thin client over the Chatsune backend voice-proxy routes for Mistral.
// All calls go through the backend — the Mistral API key never leaves the
// server. Matches the shape of the xai_voice api.ts.

import type { VoicePreset } from '../../../voice/types'
import { apiUrl, currentAccessToken } from '../../../../core/api/client'

// Relative path; routed through apiUrl() so VITE_API_URL is honoured. In
// split-origin Docker setups the frontend and backend live on different
// ports and a raw relative URL would hit the frontend origin.
const BASE = '/api/integrations/mistral_voice/voice'

interface ApiErrorBody { error_code?: string; message?: string; detail?: string }

function authHeaders(): Record<string, string> {
  const token = currentAccessToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function ensureOk(res: Response): Promise<Response> {
  if (res.ok) return res
  let msg = `HTTP ${res.status}`
  try {
    const body = (await res.clone().json()) as ApiErrorBody
    if (body.message) msg = body.message
    else if (body.detail) msg = body.detail
  } catch { /* non-JSON body */ }
  throw new Error(msg)
}

function filenameForMime(mimeType: string): string {
  // Keep aligned with the backend adapter's filename heuristic so the server
  // can still use the extension as a format hint when Content-Type is generic.
  if (mimeType.startsWith('audio/webm')) return 'recording.webm'
  if (mimeType.startsWith('audio/mp4')) return 'recording.m4a'
  return 'recording.wav'
}

export interface TranscribeParams { audio: Blob; mimeType: string; language?: string }

export async function transcribe({ audio, mimeType, language }: TranscribeParams): Promise<string> {
  const form = new FormData()
  const file = new File([audio], filenameForMime(mimeType), { type: mimeType || audio.type || 'audio/wav' })
  form.append('audio', file, file.name)
  if (language) form.append('language', language)
  const res = await fetch(apiUrl(`${BASE}/stt`), {
    method: 'POST',
    credentials: 'include',
    headers: authHeaders(),
    body: form,
  })
  await ensureOk(res)
  const body = (await res.json()) as { text: string }
  return body.text
}

export interface SynthesiseParams { text: string; voiceId: string }

export async function synthesise({ text, voiceId }: SynthesiseParams): Promise<Blob> {
  // Diagnostic logs — retained from the old SDK path. Brackets the full
  // round-trip so we can tell if latency is network vs JS event-loop.
  const preview = text.slice(0, 40).replace(/\s+/g, ' ')
  const httpStart = performance.now()
  console.log(`[TTS-http]  request "${preview}"`)
  const res = await fetch(apiUrl(`${BASE}/tts`), {
    method: 'POST',
    credentials: 'include',
    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, voice_id: voiceId }),
  })
  await ensureOk(res)
  const buf = await res.arrayBuffer()
  console.log(`[TTS-http]  response "${preview}" ${Math.round(performance.now() - httpStart)}ms`)
  return new Blob([buf], { type: res.headers.get('content-type') ?? 'audio/mpeg' })
}

export interface MistralVoice {
  id: string
  name: string
}

interface RawVoice { id: string; name: string; language?: string | null; gender?: string | null }

function mapVoice(raw: RawVoice): MistralVoice {
  return { id: raw.id, name: raw.name }
}

export async function listVoices(): Promise<MistralVoice[]> {
  const res = await fetch(apiUrl(`${BASE}/voices`), {
    method: 'GET',
    credentials: 'include',
    headers: authHeaders(),
  })
  await ensureOk(res)
  const body = (await res.json()) as { voices: RawVoice[] }
  return body.voices.map(mapVoice)
}

export async function cloneVoice({ audio, name }: {
  audio: Blob
  name: string
}): Promise<MistralVoice> {
  const form = new FormData()
  const mimeType = audio.type || 'audio/wav'
  const file = new File([audio], filenameForMime(mimeType), { type: mimeType })
  form.append('audio', file, file.name)
  form.append('name', name)
  const res = await fetch(apiUrl(`${BASE}/clone`), {
    method: 'POST',
    credentials: 'include',
    headers: authHeaders(),
    body: form,
  })
  await ensureOk(res)
  const body = (await res.json()) as RawVoice
  return mapVoice(body)
}

export async function deleteVoice(voiceId: string): Promise<void> {
  const res = await fetch(apiUrl(`${BASE}/voices/${encodeURIComponent(voiceId)}`), {
    method: 'DELETE',
    credentials: 'include',
    headers: authHeaders(),
  })
  await ensureOk(res)
}

export function toVoicePreset(v: MistralVoice): VoicePreset {
  // Mistral voices are multilingual; default to 'en' as the primary language
  // since the API does not guarantee a single-language label per voice.
  return { id: v.id, name: v.name, language: 'en' }
}
