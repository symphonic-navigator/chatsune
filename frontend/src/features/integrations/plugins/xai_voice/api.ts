// Thin client over the Chatsune backend voice-proxy routes for xAI.
// xAI does not send CORS headers; all calls go through the backend.

import type { VoicePreset } from '../../../voice/types'
import { currentAccessToken } from '../../../../core/api/client'

const BASE = '/api/integrations/xai_voice/voice'

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

export interface TranscribeParams { audio: Blob; language?: string }

export async function transcribeXai({ audio, language }: TranscribeParams): Promise<string> {
  const form = new FormData()
  form.append('audio', audio, 'audio.wav')
  if (language) form.append('language', language)
  const res = await fetch(`${BASE}/stt`, {
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

export async function synthesiseXai({ text, voiceId }: SynthesiseParams): Promise<Blob> {
  const res = await fetch(`${BASE}/tts`, {
    method: 'POST',
    credentials: 'include',
    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, voice_id: voiceId }),
  })
  await ensureOk(res)
  const buf = await res.arrayBuffer()
  return new Blob([buf], { type: res.headers.get('content-type') ?? 'audio/mpeg' })
}

export interface XaiVoice {
  id: string
  name: string
  language: string | null
  gender: string | null
}

export async function listXaiVoices(): Promise<XaiVoice[]> {
  const res = await fetch(`${BASE}/voices`, {
    method: 'GET',
    credentials: 'include',
    headers: authHeaders(),
  })
  await ensureOk(res)
  const body = (await res.json()) as { voices: XaiVoice[] }
  return body.voices
}

export function toVoicePreset(v: XaiVoice): VoicePreset {
  return { id: v.id, name: v.name, language: v.language ?? 'en' }
}
