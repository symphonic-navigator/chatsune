// Thin client over the Chatsune backend voice-proxy routes for nano-gpt
// (xAI backend). nano-gpt does not send CORS headers; all calls go
// through the backend.

import type { VoicePreset } from '../../../voice/types'
import { apiUrl, currentAccessToken } from '../../../../core/api/client'

const BASE = '/api/integrations/nano_gpt_voice_xai/voice'

interface ApiErrorBody { error_code?: string; message?: string }

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
  } catch { /* non-JSON body */ }
  throw new Error(msg)
}

function filenameForMime(mimeType: string): string {
  if (mimeType.startsWith('audio/webm')) return 'audio.webm'
  if (mimeType.startsWith('audio/mp4')) return 'audio.m4a'
  return 'audio.wav'
}

export interface TranscribeParams { audio: Blob; mimeType: string; language?: string }

export async function transcribeNanoGptXai(
  { audio, mimeType, language }: TranscribeParams,
): Promise<string> {
  const form = new FormData()
  const file = new File([audio], filenameForMime(mimeType), { type: mimeType })
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

export async function synthesiseNanoGptXai(
  { text, voiceId }: SynthesiseParams,
): Promise<Blob> {
  const res = await fetch(apiUrl(`${BASE}/tts`), {
    method: 'POST',
    credentials: 'include',
    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, voice_id: voiceId }),
  })
  await ensureOk(res)
  const buf = await res.arrayBuffer()
  return new Blob([buf], { type: res.headers.get('content-type') ?? 'audio/mpeg' })
}

export interface NanoGptXaiVoice {
  id: string
  name: string
  language: string | null
  gender: string | null
}

export async function listNanoGptXaiVoices(): Promise<NanoGptXaiVoice[]> {
  const res = await fetch(apiUrl(`${BASE}/voices`), {
    method: 'GET',
    credentials: 'include',
    headers: authHeaders(),
  })
  await ensureOk(res)
  const body = (await res.json()) as { voices: NanoGptXaiVoice[] }
  return body.voices
}

export function toVoicePreset(v: NanoGptXaiVoice): VoicePreset {
  return { id: v.id, name: v.name, language: v.language ?? 'en' }
}
