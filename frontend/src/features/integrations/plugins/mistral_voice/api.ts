// Thin wrapper around @mistralai/mistralai. Browser-side, BYOK. All calls
// take the API key per invocation — the secret lives only in the secrets store.

import { Mistral } from '@mistralai/mistralai'
import type {
  AudioTranscriptionRequest,
  TranscriptionResponse,
  SpeechRequest,
  VoiceCreateRequest,
  VoiceResponse,
} from '@mistralai/mistralai/models/components'
import type {
  SpeechResponse,
  ListVoicesV1AudioVoicesGetRequest,
} from '@mistralai/mistralai/models/operations'

function client(apiKey: string): Mistral {
  return new Mistral({ apiKey })
}

export interface TranscribeParams {
  apiKey: string
  audio: Blob
  language?: string
}

export async function transcribe({ apiKey, audio, language }: TranscribeParams): Promise<string> {
  const file = new File([audio], 'recording.wav', { type: audio.type || 'audio/wav' })

  const request: AudioTranscriptionRequest = {
    model: 'voxtral-mini-latest',
    file,
    ...(language != null ? { language } : {}),
  }

  const result: TranscriptionResponse = await client(apiKey).audio.transcriptions.complete(request)
  return result.text
}

export interface SynthesiseParams {
  apiKey: string
  text: string
  voiceId: string
}

export async function synthesise({ apiKey, text, voiceId }: SynthesiseParams): Promise<Blob> {
  const request: SpeechRequest = {
    // SDK README confirms voxtral-mini-latest as the TTS model identifier
    // (same name as the STT model — Voxtral is a unified speech model)
    model: 'voxtral-mini-latest',
    input: text,
    voiceId,
    stream: false,
  }

  // SpeechResponse carries base64-encoded audio data
  const result = await client(apiKey).audio.speech.complete(request) as SpeechResponse
  const binary = atob(result.audioData)
  const bytes = Uint8Array.from(binary, (ch) => ch.charCodeAt(0))
  return new Blob([bytes], { type: 'audio/mpeg' })
}

export interface MistralVoice {
  id: string
  name: string
}

function mapVoice(raw: VoiceResponse): MistralVoice {
  return { id: raw.id, name: raw.name }
}

export async function listVoices(apiKey: string): Promise<MistralVoice[]> {
  const PAGE_SIZE = 100
  const voices: MistralVoice[] = []
  let offset = 0

  // The API defaults to 10 per page; paginate with offset/limit until all pages consumed
  while (true) {
    const request: ListVoicesV1AudioVoicesGetRequest = { limit: PAGE_SIZE, offset }
    const page = await client(apiKey).audio.voices.list(request)
    voices.push(...page.items.map(mapVoice))
    if (page.page >= page.totalPages) break
    offset += PAGE_SIZE
  }

  return voices
}

export async function cloneVoice({ apiKey, audio, name }: {
  apiKey: string
  audio: Blob
  name: string
}): Promise<MistralVoice> {
  // The SDK create endpoint expects base64-encoded audio, not a File/FormData upload.
  const buffer = await audio.arrayBuffer()
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i])
  const sampleAudio = btoa(binary)

  const request: VoiceCreateRequest = {
    name,
    sampleAudio,
    sampleFilename: 'sample.wav',
  }
  const result: VoiceResponse = await client(apiKey).audio.voices.create(request)
  return mapVoice(result)
}

export async function deleteVoice(apiKey: string, voiceId: string): Promise<void> {
  await client(apiKey).audio.voices.delete({ voiceId })
}
